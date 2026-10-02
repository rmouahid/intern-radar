"""The application kit as JSON, for the in-browser form filler.

The filler (a userscript in the candidate's own Safari) finds the offer from
the `#radar=<ref>` fragment the kit adds to the form link, or from the form
URL itself, then fills the form; the candidate submits.
"""

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from intern_radar.answers import merged, offer_answers
from intern_radar.candidate import Candidate
from intern_radar.config import Profile
from intern_radar.models import ScoredJob
from intern_radar.store import Store

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
MONTHS = {
    m: i
    for i, names in enumerate(
        (
            ("jan", "janv"), ("feb", "fév", "fev"), ("mar", "mars"),
            ("apr", "avr"), ("may", "mai"), ("jun", "juin"), ("jul", "juil"),
            ("aug", "aoû", "aou"), ("sep", "sept"), ("oct",), ("nov",),
            ("dec", "déc"),
        ),
        start=1,
    )
    for m in names
}  # fmt: skip


def posting_key(url: str) -> str | None:
    """The ATS posting id in a Greenhouse, Lever or Ashby form URL."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for name in ("gh_jid", "token"):
        if query.get(name, [""])[0].isdigit():
            return query[name][0]
    if "greenhouse.io" in parsed.netloc:
        match = re.search(r"/jobs/(\d+)", parsed.path)
        if match:
            return match.group(1)
    if "lever.co" in parsed.netloc or "ashbyhq.com" in parsed.netloc:
        match = UUID_RE.search(parsed.path)
        if match:
            return match.group(0)
    return None


def find_ref(store: Store, url: str) -> int | None:
    key = posting_key(url)
    if key is None:
        return None
    row = store._db.execute(
        "SELECT rowid FROM jobs WHERE id LIKE ? AND source IN"
        " ('greenhouse', 'lever', 'ashby') ORDER BY score IS NULL, score DESC LIMIT 1",
        (f"%:{key}",),
    ).fetchone()
    return row["rowid"] if row else None


def month_year(text: str) -> tuple[int | None, int | None]:
    """'Sept. 2028' -> (9, 2028)."""
    year = re.search(r"(19|20)\d\d", text)
    word = re.search(r"[A-Za-zÀ-ÿ]+", text)
    month = None
    if word:
        name = word.group(0).lower()
        month = MONTHS.get(name[:4]) or MONTHS.get(name[:3])
    return month, int(year.group(0)) if year else None


def _url(value: str) -> str:
    value = value.strip()
    if value and not value.startswith(("http://", "https://")):
        return "https://" + value
    return value


def kit_payload(
    store: Store,
    scored: ScoredJob,
    ref: int,
    profile: Profile,
    candidate: Candidate | None,
    language: str,
    base: str,
) -> dict[str, Any]:
    """Everything the filler needs; `base` is the app's address."""
    job = scored.job
    bank = merged(store.answers(), profile, candidate)
    standard = {a.key: a.value for a in bank}
    first, _, last = standard["full_name"].strip().partition(" ")
    city, _, country = standard["location"].partition(",")
    degree = standard["degree"]
    discipline = degree.rsplit(",", 1)[-1].strip() if "," in degree else degree
    graduation = month_year(standard["graduation"])
    dates = candidate.education[0].dates if candidate and candidate.education else ""
    parts = re.split(r"\s*[–-]\s*", dates) if dates else []
    studies = (
        month_year(parts[0]) if parts else (None, None),
        month_year(parts[-1]) if len(parts) > 1 else graduation,
    )
    why = store.why(job.id)
    documents = {
        kind: f"{base}/files/{kind}/{ref}"
        for kind, saved in (
            ("cv", store.resume(job.id)),
            ("letter", store.letter(job.id)),
        )
        if saved is not None
    }
    return {
        "ref": ref,
        "offer": {
            "company": job.company,
            "title": job.title,
            "location": job.location,
            "ats": job.source,
            "page": f"{base}/offers/{ref}#kit",
        },
        "fields": {
            "first_name": first,
            "last_name": last,
            "full_name": standard["full_name"],
            "email": standard["email"],
            "phone": standard["phone"],
            "city": city.strip(),
            "country": country.strip(),
            "location": standard["location"],
            "linkedin": _url(standard["linkedin"]),
            "github": _url(standard["github"]),
            "school": standard["school"].split(",")[0].strip(),
            "degree": degree,
            "degree_level": "Master's Degree" if "master" in degree.lower() else "",
            "discipline": discipline,
            "graduation_month": graduation[0],
            "graduation_year": graduation[1],
            "education_start_month": studies[0][0],
            "education_start_year": studies[0][1],
            "education_end_month": studies[1][0],
            "education_end_year": studies[1][1],
            "internship_start_month": profile.window_start.month,
            "internship_start_year": profile.window_start.year,
            "internship_end_month": profile.window_end.month,
            "internship_end_year": profile.window_end.year,
            "languages": standard["languages"],
            "heard_from": standard["heard_from"],
        },
        "answers": [
            {"question": a.label if language == "fr" else a.question, "answer": a.value}
            for a in bank
            if a.value
        ]
        + [
            {"question": q, "answer": v}
            for q, v in offer_answers(
                scored.assessment.work_authorisation, job.location, profile, language
            )
        ],
        "work_authorisation": scored.assessment.work_authorisation,
        "why": why.text if why else "",
        "documents": documents,
    }
