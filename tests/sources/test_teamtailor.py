import httpx
import pytest

from intern_radar.models import Company, Job
from intern_radar.sources.base import SourceError
from intern_radar.sources.teamtailor import TeamtailorSource
from tests.factories import mock_client

FEED = "https://multiversecomputing.teamtailor.com/jobs.rss"
COMPANY = Company(
    "Multiverse Computing", "B", "teamtailor", {"account": "multiversecomputing"}
)

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:tt="https://teamtailor.com/locations">
  <channel>
    <title>MULTIVERSE COMPUTING</title>
    <item>
      <title>Machine Learning Engineer Intern</title>
      <description>&lt;p&gt;Compress LLMs with tensor networks.&lt;/p&gt;</description>
      <pubDate>Fri, 16 Oct 2026 12:14:14 +0200</pubDate>
      <link>https://multiversecomputing.teamtailor.com/jobs/6292402-machine-learning-engineer-intern</link>
      <remoteStatus>hybrid</remoteStatus>
      <guid>1adf9b52-6caa-4bd4-90bf-20be749b55d3</guid>
      <tt:locations>
        <tt:location>
          <tt:city>Donostia</tt:city>
          <tt:country>Spain</tt:country>
        </tt:location>
        <tt:location>
          <tt:city>Madrid</tt:city>
          <tt:country>Spain</tt:country>
        </tt:location>
      </tt:locations>
    </item>
    <item>
      <title>DevOps Engineer (Mid)</title>
      <description>&lt;p&gt;x&lt;/p&gt;</description>
      <pubDate>Thu, 01 Oct 2026 09:55:17 +0200</pubDate>
      <link>https://multiversecomputing.teamtailor.com/jobs/8557830-devops-engineer-mid</link>
      <guid>3eaa713d</guid>
    </item>
    <item>
      <title>Quantum Research Internship</title>
      <description></description>
      <pubDate>not a date</pubDate>
      <link>https://multiversecomputing.teamtailor.com/jobs/8197577-quantum</link>
      <remoteStatus>fully</remoteStatus>
      <guid>c0ffee</guid>
    </item>
  </channel>
</rss>
"""


def rss(body: str, status: int = 200):
    return lambda request: httpx.Response(
        status, text=body, headers={"content-type": "application/rss+xml"}
    )


def test_fetch_maps_teamtailor_jobs():
    client = mock_client({f"GET {FEED}": rss(RSS)})
    jobs = TeamtailorSource(client).fetch(
        COMPANY, known_ids={"teamtailor:multiversecomputing:8197577"}
    )
    assert jobs == [
        Job(
            id="teamtailor:multiversecomputing:6292402",
            company="Multiverse Computing",
            tier="B",
            title="Machine Learning Engineer Intern",
            location="Donostia, Spain; Madrid, Spain",
            url="https://multiversecomputing.teamtailor.com/jobs/6292402-machine-learning-engineer-intern",
            description="Compress LLMs with tensor networks.",
            source="teamtailor",
            posted_at="2026-10-16",
        )
    ]


def test_fetch_handles_remote_jobs_and_bad_dates():
    client = mock_client({f"GET {FEED}": rss(RSS)})
    jobs = TeamtailorSource(client).fetch(COMPANY, known_ids=set())
    remote = jobs[1]
    assert remote.id == "teamtailor:multiversecomputing:8197577"
    assert remote.location == "Remote"
    assert remote.posted_at is None


def test_fetch_rejects_invalid_feeds():
    client = mock_client({f"GET {FEED}": rss("<html>maintenance</rss>")})
    with pytest.raises(SourceError, match="invalid RSS"):
        TeamtailorSource(client).fetch(COMPANY, known_ids=set())


def test_fetch_wraps_http_errors():
    with pytest.raises(SourceError, match="404"):
        TeamtailorSource(mock_client({})).fetch(COMPANY, known_ids=set())
