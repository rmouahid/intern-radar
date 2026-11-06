"""Record one real answer per source adapter into tests/cassettes/.

    poetry run python scripts/record_cassettes.py                 # every adapter
    poetry run python scripts/record_cassettes.py greenhouse lever
    poetry run python scripts/record_cassettes.py --company workday="NVIDIA"

Each adapter fetches one company from config/companies.yaml against the real
API (1 s between two requests to a host). Requests and answers are saved
with secrets removed and long listings cut; the jobs expected by the tests
are computed by replaying the saved file. Needs network access, and the
Adzuna keys of config/profile.yaml for the adzuna cassette.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from intern_radar.cassette import (  # noqa: E402
    RecordingTransport,
    ReplayTransport,
    build_source,
    job_summary,
    redact,
    shorten,
)
from intern_radar.config import load_companies, load_profile  # noqa: E402
from intern_radar.http import Throttle, make_client  # noqa: E402
from intern_radar.sources import SOURCE_NAMES  # noqa: E402
from intern_radar.sources.adzuna import company_lookup, search_terms  # noqa: E402

OUT = ROOT / "tests" / "cassettes"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("adapters", nargs="*", help="adapters to record (default: all)")
    parser.add_argument(
        "--company",
        action="append",
        default=[],
        help='adapter="Company name" to record',
    )
    args = parser.parse_args()

    companies = load_companies(ROOT / "config" / "companies.yaml", SOURCE_NAMES)
    profile = load_profile(ROOT / "config" / "profile.yaml")
    chosen = dict(item.split("=", 1) for item in args.company)
    adapters = args.adapters or sorted(SOURCE_NAMES - {"none"})
    lookup = {name: list(value) for name, value in company_lookup(companies).items()}
    OUT.mkdir(parents=True, exist_ok=True)

    for adapter in adapters:
        candidates = [c for c in companies if c.source == adapter]
        if adapter in chosen:
            candidates = [c for c in candidates if c.name == chosen[adapter]]
        if not candidates:
            print(f"{adapter}: no company in companies.yaml, skipped")
            continue
        setup: dict = {}
        secrets: dict = {}
        if adapter == "adzuna":
            setup = {"terms": search_terms(companies), "lookup": lookup}
            secrets = {
                "app_id": profile.adzuna_app_id,
                "app_key": profile.adzuna_app_key,
            }
        elif adapter == "simplify":
            setup = {
                "lookup": lookup,
                "window": [str(profile.window_start), str(profile.window_end)],
            }
        for company in candidates[:6]:  # the first one with an internship
            exchanges, jobs = record(adapter, company, setup, secrets)
            if jobs:
                break
            print(f"{adapter}: {company.name} has no internship now, next company")
        write(adapter, company, setup, exchanges, jobs)


def record(adapter, company, setup, secrets):
    """Fetch for real, cut the answers, then replay them for the expected jobs."""
    recorder = RecordingTransport()
    with make_client(Throttle(1.0), recorder) as client:
        real = build_source(adapter, client, setup, secrets).fetch(company, set())
    # Keep the listing items of a few real jobs (their URLs, or the tail of
    # their ids), then replay the cut cassette for the expected jobs.
    keep = tuple(j.url for j in real[:8] if j.url) + tuple(
        j.id.rsplit(":", 1)[-1] for j in real[:8]
    )
    exchanges = redact(shorten(recorder.exchanges, keep), list(secrets.values()))
    with make_client(Throttle(0), ReplayTransport(exchanges)) as client:
        jobs = build_source(adapter, client, setup, {}).fetch(company, set())
    return exchanges, jobs


def write(adapter, company, setup, exchanges, jobs) -> None:
    cassette = {
        "adapter": adapter,
        "company": {
            "name": company.name,
            "tier": company.tier,
            "source": company.source,
            "params": company.params,
        },
        "setup": setup,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "exchanges": exchanges,
        "expected": [job_summary(job) for job in jobs],
    }
    path = OUT / f"{adapter}.json"
    path.write_text(
        json.dumps(cassette, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    size = path.stat().st_size // 1024
    print(
        f"{adapter}: {company.name}, {len(exchanges)} requests,"
        f" {len(jobs)} jobs, {size} KB"
    )


if __name__ == "__main__":
    main()
