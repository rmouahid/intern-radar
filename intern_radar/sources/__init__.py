"""Source plugins and their registry."""

from datetime import date

import httpx

from intern_radar.config import Profile
from intern_radar.models import Company
from intern_radar.prefilter import ListingRules
from intern_radar.sources.adzuna import AdzunaSource, company_lookup, search_terms
from intern_radar.sources.amazon import AmazonSource
from intern_radar.sources.ashby import AshbySource
from intern_radar.sources.base import Source
from intern_radar.sources.greenhouse import GreenhouseSource
from intern_radar.sources.lever import LeverSource
from intern_radar.sources.microsoft import MicrosoftSource
from intern_radar.sources.smartrecruiters import SmartRecruitersSource
from intern_radar.sources.workable import WorkableSource
from intern_radar.sources.workday import WorkdaySource

SOURCE_NAMES = frozenset(
    {
        "greenhouse",
        "lever",
        "ashby",
        "workable",
        "smartrecruiters",
        "workday",
        "amazon",
        "microsoft",
        "adzuna",
        "none",
    }
)


def build_sources(
    client: httpx.Client, companies: list[Company], profile: Profile
) -> dict[str, Source]:
    rules = ListingRules(
        profile.extra_excluded_title_words,
        profile.window_start.year,
        profile.max_offer_age_days,
        date.today(),
    )
    return {
        "greenhouse": GreenhouseSource(client, rules),
        "lever": LeverSource(client),
        "ashby": AshbySource(client),
        "workable": WorkableSource(client),
        "smartrecruiters": SmartRecruitersSource(client, rules),
        "workday": WorkdaySource(client, rules),
        "amazon": AmazonSource(client),
        "microsoft": MicrosoftSource(client),
        "adzuna": AdzunaSource(
            client,
            profile.adzuna_app_id,
            profile.adzuna_app_key,
            company_lookup(companies),
            search_terms(companies),
            discovery=profile.discovery,
        ),
    }
