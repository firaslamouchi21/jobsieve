import argparse
import json
import os
import sys
from . import db, watchlist


def parse_args(argv: list[str]):
    p = argparse.ArgumentParser(prog="jobsieve")
    p.add_argument("--config", default=os.environ.get("CONFIG_DIR", "./config"))
    p.add_argument("--data", default=os.environ.get("DATA_DIR", "./data"))

    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run")
    run.add_argument(
        "--provider",
        choices=["groq", "anthropic", "gemini", "openai"],
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

    discover = sub.add_parser("discover", help="search the web for company career boards and add them to the watchlist")
    discover.add_argument("--keyword", nargs="+", required=True, dest="keywords")
    discover.add_argument("--place", nargs="+", default=None, dest="places", help="cities or countries to add to each search")

    watch = sub.add_parser("watch", help="companies whose career boards the 'boards' source reads")
    watch_sub = watch.add_subparsers(dest="watch_cmd", required=True)
    for action in ("add", "remove"):
        item = watch_sub.add_parser(action)
        item.add_argument("board", choices=watchlist.BOARDS)
        item.add_argument("company", help="the name in the board URL, e.g. careem for boards.greenhouse.io/careem")
    watch_sub.add_parser("list")
    starter = watch_sub.add_parser("starter", help="add a ready-made list of companies (no name: show the lists)")
    starter.add_argument("name", nargs="?")
    page_add = watch_sub.add_parser("add-page", help="a careers or listing page to read politely (needs structured job data)")
    page_add.add_argument("url")
    page_remove = watch_sub.add_parser("remove-page")
    page_remove.add_argument("url")
    from_page = watch_sub.add_parser("from-page", help="read a company careers page and add the job board it uses")
    from_page.add_argument("url")
    check = watch_sub.add_parser("check", help="ask each board whether the company exists and count its open jobs")

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

    start_cmd = sub.add_parser("start", help="start the API and the dashboard together, no Docker; needs jobsieve[api,ui]")
    start_cmd.add_argument("--demo", action="store_true", help="use fake demo data in ./demo-data (nothing of yours is touched)")
    start_cmd.add_argument("--api-port", type=int, default=8000)
    start_cmd.add_argument("--ui-port", type=int, default=8501)
    start_cmd.add_argument("--no-browser", action="store_true")

    sub.add_parser("mcp", help="serve Jobsieve to AI agents over MCP (stdio); needs jobsieve[mcp]")

    digest = sub.add_parser("digest", help="show new matches since the last digest; --send delivers them")
    digest.add_argument("--send", action="store_true", help="send through your webhook, email or Telegram and move the marker forward")

    schedule_cmd = sub.add_parser("schedule", help="run on a timer in the foreground")
    schedule_cmd.add_argument("--every-hours", type=float, required=True)

    jobs_cmd = sub.add_parser("jobs", help="list saved jobs")
    jobs_cmd.add_argument("--status", nargs="+", choices=db.STATUSES, help="default: everything except hidden")
    jobs_cmd.add_argument("--eligibility", nargs="+", choices=["eligible", "unknown", "not_eligible", "unchecked"])
    jobs_cmd.add_argument("--limit", type=int, default=30)

    tailor_cmd = sub.add_parser("tailor", help="CV suggestions and a cover letter draft for one job (uses your AI key or local model)")
    tailor_cmd.add_argument("job_hash")
    tailor_cmd.add_argument("--provider", choices=["groq", "anthropic", "gemini", "openai"], default="groq")
    tailor_cmd.add_argument("--out", default="-", help="write Markdown to this file (default: print)")

    mark = sub.add_parser("mark", help="set a job's status (and optionally a note)")
    mark.add_argument("job_hash", help="the job_hash shown by 'jobs' or 'fetch --json'; a unique start is enough")
    mark.add_argument("status", choices=db.STATUSES)
    mark.add_argument("--note")

    export = sub.add_parser("export")
    export.add_argument("--format", choices=["json", "csv"], default="json")
    export.add_argument("--limit", type=int, default=200)
    export.add_argument("--eligibility", nargs="+", choices=["eligible", "unknown", "not_eligible", "unchecked"])
    export.add_argument("--out", default="-")
    export.add_argument("--status", nargs="+", choices=db.STATUSES)

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

    rows = [db.csv_row(r) for r in rows]

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


def run_watch(args) -> int:
    from .sources.boards import fetch_board
    from .util import sleep_delay

    try:
        if args.watch_cmd == "add":
            print("added" if watchlist.add(args.board, args.company) else "already on the watchlist")
        elif args.watch_cmd == "remove":
            print("removed" if watchlist.remove(args.board, args.company) else "not on the watchlist")
        elif args.watch_cmd == "starter":
            lists = watchlist.starter_lists()
            if not args.name:
                for name, data in lists.items():
                    print(f"{name}: {len(data['companies'])} companies. {data['description']}")
            else:
                print(f"{watchlist.add_starter(args.name)} companies added")
        elif args.watch_cmd == "add-page":
            print("added" if watchlist.add_page(args.url) else "already on the list")
        elif args.watch_cmd == "remove-page":
            print("removed" if watchlist.remove_page(args.url) else "not on the list")
        elif args.watch_cmd == "from-page":
            from . import careers

            found = careers.add_from_page(args.url)
            if not found:
                print("no Greenhouse, Lever, Ashby or SmartRecruiters board found on that page")
                return 1
            for board, slug, added in found:
                print(f"{'added' if added else 'already listed'}: {board} {slug}")
        elif args.watch_cmd == "list":
            for row in watchlist.load():
                print(f"{row['board']:16} {row['slug']}  ({row.get('added_by', 'manual')})")
            for page in watchlist.load_pages():
                print(f"{'page':16} {page}")
        else:
            failed = 0
            for row in watchlist.load():
                try:
                    print(f"ok      {row['board']:16} {row['slug']}: {len(fetch_board(row['board'], row['slug']))} jobs")
                except Exception as error:
                    failed += 1
                    print(f"FAILED  {row['board']:16} {row['slug']}: {str(error)[:100]}")
                sleep_delay()
            return 1 if failed else 0
    except (watchlist.WatchlistError, careers_error()) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


def careers_error():
    from .careers import CareerPageError

    return CareerPageError


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

    if args.cmd == "watch":
        return run_watch(args)

    if args.cmd == "discover":
        from . import discovery

        try:
            added = discovery.search(args.keywords, args.places)
        except Exception as error:
            print(f"search failed: {error}", file=sys.stderr)
            return 3
        print(f"{added} new companies added to the watchlist (see: jobsieve watch list)")
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

    if args.cmd == "start":
        from . import launcher

        if args.demo:
            if os.environ["DATA_DIR"] == "./data":
                os.environ["DATA_DIR"] = "./demo-data"
            from . import demo

            print(f"{demo.seed()} demo jobs ready in {os.environ['DATA_DIR']}", file=sys.stderr)
        return launcher.start(args.api_port, args.ui_port, not args.no_browser)

    if args.cmd == "mcp":
        from . import mcp_server

        mcp_server.main()
        return 0

    if args.cmd == "digest":
        from . import notifications

        db.init()
        if args.send:
            if not notifications.alerts_configured():
                print("no webhook, email or Telegram is configured", file=sys.stderr)
                return 2
            print(f"{notifications.check_and_notify()} matches sent")
            return 0
        matches = notifications.pending_matches()
        print(notifications.render_markdown(matches, limit=50) if matches else "nothing new since the last digest")
        return 0

    if args.cmd == "schedule":
        from . import schedule

        try:
            schedule.loop(args.every_hours)
        except KeyboardInterrupt:
            pass
        return 0

    if args.cmd == "jobs":
        db.init()
        for job in db.list_jobs(limit=args.limit, eligibility=args.eligibility, status=args.status):
            verdict = job.get("eligibility") or "unchecked"
            print(
                f"{job['job_hash'][:10]}  {job.get('status') or 'new':12} {verdict:12} "
                f"{job.get('score') or 0:>2}  {job['title'][:50]} | {job.get('company') or ''} | {job['freshness']['label']}"
            )
        return 0

    if args.cmd == "tailor":
        from . import tailor

        db.init()
        matches = db.find_hashes(args.job_hash)
        if len(matches) != 1:
            print("no job matches that id" if not matches else "that id matches several jobs; use more characters", file=sys.stderr)
            return 2
        keys = {args.provider: os.environ.get({"groq": "GROQ_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY"}[args.provider], "")}
        try:
            output = tailor.tailor_job(matches[0], args.provider, keys)
        except tailor.TailorError as error:
            print(str(error), file=sys.stderr)
            return 2
        text = tailor.to_markdown(db.get_job(matches[0]), output)
        if args.out == "-":
            print(text)
        else:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(text)
        return 0

    if args.cmd == "mark":
        db.init()
        matches = db.find_hashes(args.job_hash)
        if len(matches) != 1:
            print("no job matches that id" if not matches else "that id matches several jobs; use more characters", file=sys.stderr)
            return 2
        try:
            job = db.set_status(matches[0], args.status, args.note)
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 2
        print(f"{job['title']}: {job['status']}")
        return 0

    if args.cmd == "export":
        db.init()
        rows = db.list_jobs(limit=args.limit, eligibility=args.eligibility, status=args.status)
        if args.format == "json":
            write_json(rows, args.out)
        else:
            write_csv(rows, args.out)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
