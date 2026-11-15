import argparse
import json
import os
import sys
from . import db


def parse_args(argv: list[str]):
    p = argparse.ArgumentParser(prog="jobsieve")
    p.add_argument("--config", default=os.environ.get("CONFIG_DIR", "./config"))
    p.add_argument("--data", default=os.environ.get("DATA_DIR", "./data"))

    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run")
    run.add_argument(
        "--provider",
        choices=["groq", "anthropic", "gemini"],
        default="groq",
    )
    run.add_argument("--api-key", default=os.environ.get("GROQ_API_KEY", ""))
    run.add_argument("--groq-api-key", default=os.environ.get("GROQ_API_KEY", ""))
    run.add_argument(
        "--anthropic-api-key",
        default=os.environ.get("ANTHROPIC_API_KEY", ""),
    )
    run.add_argument("--gemini-api-key", default=os.environ.get("GEMINI_API_KEY", ""))
    run.add_argument("--lite", action="store_true")
    run.add_argument("--sources", nargs="+", default=None, help="sources to use (default: ddg); see 'jobsieve sources'")
    run.add_argument("--sites", nargs="+", default=None, help="domains to search (default: config/sites.txt, then built-in list)")
    run.add_argument("--keywords", nargs="+", default=None, help="search keywords (default: config/keywords.txt)")
    run.add_argument("--cv-file", default=None, help="text file with your CV (default: config/cv.txt)")

    fetch = sub.add_parser("fetch", help="fetch listings from sources without scoring or the API server")
    fetch.add_argument("--source", nargs="+", required=True, dest="sources")
    fetch.add_argument("--keyword", nargs="+", default=[], dest="keywords")
    fetch.add_argument("--site", nargs="+", default=None, dest="sites", help="domains for the ddg source")
    fetch.add_argument("--limit", type=int, default=50, help="maximum listings per source")
    fetch.add_argument("--json", action="store_true", help="print machine-readable JSON")
    fetch.add_argument("--no-store", action="store_true", help="do not save to the database")

    sub.add_parser("sources", help="list available sources")

    profile_cmd = sub.add_parser("profile", help="show or change your saved profile")
    profile_sub = profile_cmd.add_subparsers(dest="profile_cmd", required=True)
    show = profile_sub.add_parser("show")
    show.add_argument("--json", action="store_true")
    setter = profile_sub.add_parser("set", help="change profile fields; saved jobs are re-checked")
    setter.add_argument("--home-country")
    setter.add_argument("--work-authorization", nargs="+", metavar="PLACE", help="countries or regions where you can work without sponsorship, e.g. GCC EU")
    setter.add_argument("--needs-visa", action=argparse.BooleanOptionalAction, default=None)
    setter.add_argument("--open-to-relocation", nargs="+", metavar="PLACE")
    setter.add_argument("--work-modes", nargs="+", metavar="MODE", help="remote hybrid onsite")
    setter.add_argument("--timezone-offset", type=float, help="your UTC offset in hours, e.g. 3")
    setter.add_argument("--max-timezone-diff", type=float, help="largest accepted gap from a job's timezone, in hours")
    setter.add_argument("--salary-floor", type=float, help="minimum yearly pay")
    setter.add_argument("--salary-currency")
    setter.add_argument("--seniority", nargs="+", metavar="LEVEL")
    setter.add_argument("--languages", nargs="+")
    setter.add_argument("--dealbreakers", nargs="+", metavar="WORD")
    setter.add_argument("--exclude-companies", nargs="+", metavar="NAME")
    setter.add_argument("--keywords", nargs="+")
    setter.add_argument("--cv-file")
    setter.add_argument("--sites", nargs="+")
    setter.add_argument("--sources", nargs="+", dest="profile_sources")
    profile_sub.add_parser("reevaluate", help="re-check saved jobs against the profile")

    export = sub.add_parser("export")
    export.add_argument("--format", choices=["json", "csv"], default="json")
    export.add_argument("--limit", type=int, default=200)
    export.add_argument("--eligibility", nargs="+", choices=["eligible", "unknown", "not_eligible", "unchecked"])
    export.add_argument("--out", default="-")

    return p.parse_args(argv)


def write_json(rows: list[dict], out_path: str):
    payload = json.dumps(rows, ensure_ascii=False, indent=2)
    if out_path == "-":
        sys.stdout.write(payload)
        sys.stdout.write("\n")
        return
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(payload)
        f.write("\n")


def write_csv(rows: list[dict], out_path: str):
    import csv

    fieldnames = []
    for r in rows:
        for k in r.keys():
            if k not in fieldnames:
                fieldnames.append(k)

    if out_path == "-":
        w = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)
        return

    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


PROFILE_FLAGS = {
    "home_country": "home_country",
    "work_authorization": "work_authorization",
    "needs_visa": "needs_visa",
    "open_to_relocation": "open_to_relocation",
    "work_modes": "work_modes",
    "timezone_offset": "timezone_offset",
    "max_timezone_diff": "max_timezone_diff",
    "salary_floor": "salary_floor",
    "salary_currency": "salary_currency",
    "seniority": "seniority",
    "languages": "languages",
    "dealbreakers": "dealbreakers",
    "exclude_companies": "excluded_companies",
    "keywords": "keywords",
    "sites": "sites",
    "profile_sources": "sources",
}


def run_profile(args) -> int:
    from . import eligibility
    from . import profile as prof

    try:
        if args.profile_cmd == "show":
            current = prof.load()
            if args.json:
                print(json.dumps(current, ensure_ascii=False, indent=2))
            else:
                print(f"profile file: {prof.profile_path()}{'' if prof.exists() else ' (not created yet)'}")
                for key, value in current.items():
                    shown = (value[:60] + "...") if isinstance(value, str) and len(value) > 60 else value
                    print(f"  {key}: {shown}")
            return 0
        if args.profile_cmd == "set":
            changes = {
                field: getattr(args, flag)
                for flag, field in PROFILE_FLAGS.items()
                if getattr(args, flag, None) is not None
            }
            if args.cv_file:
                with open(args.cv_file, "r", encoding="utf-8") as f:
                    changes["cv_text"] = f.read()
            if not changes:
                print("nothing to change; pass at least one option", file=sys.stderr)
                return 2
            saved = prof.update(changes)
        else:
            saved = prof.load()
    except (prof.ProfileError, OSError) as error:
        print(f"profile error: {error}", file=sys.stderr)
        return 2
    db.init()
    counts = eligibility.reevaluate_stored(saved)
    print(
        "saved jobs re-checked: "
        f"{counts['eligible']} eligible, {counts['unknown']} unknown, {counts['not_eligible']} not eligible",
        file=sys.stderr,
    )
    return 0


def run_fetch(args) -> int:
    from .sources import SourceError, get_source
    from .util import log_event

    try:
        chosen = [get_source(name) for name in args.sources]
    except SourceError as error:
        print(str(error), file=sys.stderr)
        return 2

    run_id = None
    if not args.no_store:
        db.init()
        run_id = db.start_run()

    output = []
    failed = 0
    for source in chosen:
        try:
            records = source.fetch(args.keywords, limit=args.limit, sites=args.sites)
        except Exception as error:
            failed += 1
            print(f"{source.name}: {error}", file=sys.stderr)
            log_event("source_failed", source=source.name, error=str(error)[:160])
            continue
        for record in records:
            item = record.to_dict()
            item["job_hash"] = db.record_hash(record)
            item["attribution"] = source.label
            item["is_new"] = None
            if not args.no_store:
                item["is_new"] = bool(db.upsert_record(record, None, "", run_id))
            output.append(item)

    if run_id:
        db.finish_run(run_id)
    if args.json:
        write_json(output, "-")
    else:
        for item in output:
            marker = "new " if item["is_new"] else "    "
            print(f"{marker}{item['title']} | {item['company']} | {item['location']} | {item['url']} (via {item['attribution']})")
        print(f"{len(output)} listings from {len(chosen) - failed} of {len(chosen)} sources", file=sys.stderr)
    return 3 if failed == len(chosen) else 0


def main(argv: list[str] | None = None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    os.environ["CONFIG_DIR"] = args.config
    os.environ["DATA_DIR"] = args.data

    if args.cmd == "run":
        from . import scraper

        keys = {
            "groq": args.groq_api_key or args.api_key or "",
            "anthropic": args.anthropic_api_key or "",
            "gemini": args.gemini_api_key or "",
        }
        cv_text = None
        if args.cv_file:
            try:
                with open(args.cv_file, "r", encoding="utf-8") as f:
                    cv_text = f.read()
            except OSError as error:
                print(f"cannot read CV file: {error}", file=sys.stderr)
                return 2
        if not scraper.try_lock():
            print("another run is already in progress; not starting", file=sys.stderr)
            return 1
        scraper.run_scrape(
            args.api_key or "",
            bool(args.lite),
            provider=args.provider,
            api_keys=keys,
            sources=args.sources,
            sites=args.sites,
            keywords=args.keywords,
            cv_text=cv_text,
            _lock_acquired=True,
        )
        return 0

    if args.cmd == "sources":
        from .sources import REGISTRY

        for source in REGISTRY.values():
            print(f"{source.name}\t{source.label}\t{source.attribution_url}")
        return 0

    if args.cmd == "fetch":
        return run_fetch(args)

    if args.cmd == "profile":
        return run_profile(args)

    if args.cmd == "export":
        db.init()
        rows = db.list_jobs(limit=args.limit, eligibility=args.eligibility)
        if args.format == "json":
            write_json(rows, args.out)
        else:
            write_csv(rows, args.out)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
