"""Teamtailor career sites (public RSS feed of the open jobs)."""

import re
import xml.etree.ElementTree as ET
from collections.abc import Container
from email.utils import parsedate_to_datetime

import httpx

from intern_radar.models import Company, Job
from intern_radar.prefilter import is_internship_title
from intern_radar.sources.base import (
    SourceError,
    collect,
    get_text,
    html_to_text,
    require_param,
)

FEED = "https://{account}.teamtailor.com/jobs.rss"
TT = "{https://teamtailor.com/locations}"
JOB_ID_RE = re.compile(r"/jobs/(\d+)")


def _text(element: ET.Element, path: str) -> str:
    return (element.findtext(path) or "").strip()


def _location(item: ET.Element) -> str:
    places = []
    for loc in item.iterfind(f"{TT}locations/{TT}location"):
        parts = (_text(loc, f"{TT}city"), _text(loc, f"{TT}country"))
        place = ", ".join(part for part in parts if part)
        if place and place not in places:
            places.append(place)
    if _text(item, "remoteStatus") == "fully":
        places.append("Remote")
    return "; ".join(places)


def _posted_at(value: str) -> str | None:
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        return None


class TeamtailorSource:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def fetch(self, company: Company, known_ids: Container[str]) -> list[Job]:
        account = require_param(company, "account")
        url = FEED.format(account=account)
        # The stdlib parser is safe here: it never fetches external entities
        # and the bundled expat (>= 2.4.1) bounds entity expansion.
        try:
            channel = ET.fromstring(get_text(self._client, url)).find("channel")
        except ET.ParseError as exc:
            raise SourceError(f"GET {url}: invalid RSS ({exc})") from exc
        items = channel.findall("item") if channel is not None else []

        def convert(item: ET.Element) -> Job | None:
            title, link = _text(item, "title"), _text(item, "link")
            match = JOB_ID_RE.search(link)
            local_id = match[1] if match else _text(item, "guid")
            job_id = f"teamtailor:{account}:{local_id}"
            if job_id in known_ids or not is_internship_title(title):
                return None
            if not link:
                raise ValueError("posting without a link")
            return Job(
                id=job_id,
                company=company.name,
                tier=company.tier,
                title=title,
                location=_location(item),
                url=link,
                description=html_to_text(_text(item, "description")),
                source="teamtailor",
                posted_at=_posted_at(_text(item, "pubDate")),
            )

        return collect(company, items, convert)
