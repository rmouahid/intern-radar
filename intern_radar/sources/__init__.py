"""Source plugins and their registry."""

import httpx

from intern_radar.config import Profile
from intern_radar.models import Company
from intern_radar.sources.ashby import AshbySource
from intern_radar.sources.base import Source
from intern_radar.sources.greenhouse import GreenhouseSource
from intern_radar.sources.lever import LeverSource
from intern_radar.sources.smartrecruiters import SmartRecruitersSource
from intern_radar.sources.workable import WorkableSource

SOURCE_NAMES = frozenset(
    {"greenhouse", "lever", "ashby", "workable", "smartrecruiters", "none"}
)


def build_sources(
    client: httpx.Client, companies: list[Company], profile: Profile
) -> dict[str, Source]:
    return {
        "greenhouse": GreenhouseSource(client),
        "lever": LeverSource(client),
        "ashby": AshbySource(client),
        "workable": WorkableSource(client),
        "smartrecruiters": SmartRecruitersSource(client),
    }
