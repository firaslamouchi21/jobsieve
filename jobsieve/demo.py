from datetime import datetime, timedelta, timezone

from . import db, eligibility
from . import profile as prof
from .sources.base import JobRecord

DEMO_PROFILE = {
    "home_country": "AE",
    "work_authorization": ["GCC"],
    "needs_visa": False,
    "open_to_relocation": ["GCC"],
    "work_modes": ["remote", "hybrid", "onsite"],
    "keywords": ["data engineer", "python"],
    "cv_text": "Data engineer with 5 years of Python, SQL and Airflow. Built pipelines for fintech and logistics teams in Dubai.",
}

DEMO_JOBS = [
    ("Senior Data Engineer", "Demo Payments", "Dubai, United Arab Emirates", False, "Python, SQL and Airflow. Based in Dubai. Hybrid.", 2, "lever"),
    ("Analytics Engineer", "Demo Logistics", "Riyadh, Saudi Arabia", False, "dbt and SQL. Onsite in Riyadh. Relocation support provided.", 9, "greenhouse"),
    ("Backend Engineer (Remote)", "Demo Cloud", "Remote", True, "Work from anywhere in the world. Python and Go.", 5, "himalayas"),
    ("Data Platform Engineer", "Demo Retail", "Remote", True, "Remote, but you must be based in the United States.", 4, "remotive"),
    ("ML Engineer", "Demo Labs", "London, United Kingdom", False, "Onsite in London. We cannot offer visa sponsorship.", 12, "ashby"),
    ("Data Engineer", "Demo Bank", "Doha, Qatar", False, "Python and Spark. Doha office.", 20, "smartrecruiters"),
    ("Software Engineer", "Demo Health", "Remote (EMEA)", True, "Remote within EMEA time zones.", 1, "jobicy"),
    ("Platform Engineer", "Demo Gov", "Washington, United States", False, "US citizenship and security clearance required.", 6, "greenhouse"),
    ("Data Analyst", "Demo Media", "Dubai, United Arab Emirates", False, "SQL and dashboards. Dubai.", 70, "lever"),
    ("DevOps Engineer", "Demo Telecom", "Abu Dhabi, United Arab Emirates", False, "Kubernetes and Terraform. Abu Dhabi.", 3, "workingnomads"),
]


def seed() -> int:
    db.init()
    profile = prof.save(DEMO_PROFILE)
    now = datetime.now(timezone.utc)
    run_id = db.start_run()
    for number, (title, company, location, remote, description, age_days, source) in enumerate(DEMO_JOBS, start=1):
        record = JobRecord(
            title=title, company=company, url=f"https://example.com/demo/{number}", source=source,
            location=location, remote=remote, description=description,
            posted_at=(now - timedelta(days=age_days)).isoformat(),
        )
        verdict = eligibility.evaluate(eligibility.job_from_record(record, description), profile)
        score = 9 if verdict["verdict"] == "eligible" else 5 if verdict["verdict"] == "unknown" else 2
        db.upsert_record(
            record, score, "demo data",  run_id, description=description,
            eligibility=verdict["verdict"], eligibility_reasons=verdict["reasons"], work_mode=verdict["work_mode"],
            profile_fingerprint=prof.fingerprint(profile),
        )
    db.finish_run(run_id)
    return len(DEMO_JOBS)
