from datetime import date
from pathlib import Path

import pytest

from intern_radar.config import (
    ConfigError,
    Thresholds,
    Weights,
    load_companies,
    load_profile,
)
from intern_radar.models import Company

SOURCES = {"greenhouse", "workday", "none"}


def write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_load_companies_keeps_extra_keys_as_params(tmp_path):
    path = write(
        tmp_path,
        "companies.yaml",
        """
- name: Anthropic
  tier: S
  source: greenhouse
  board: anthropic
- name: Meta
  tier: S
  source: none
  aliases: [Facebook]
""",
    )
    assert load_companies(path, SOURCES) == [
        Company("Anthropic", "S", "greenhouse", {"board": "anthropic"}),
        Company("Meta", "S", "none", {"aliases": ["Facebook"]}),
    ]


@pytest.mark.parametrize(
    "content, message",
    [
        ("- {name: X, tier: S}", "is missing"),
        ("- {name: X, tier: Z, source: none}", "invalid tier"),
        ("- {name: X, tier: S, source: bamboo}", "unknown source"),
        (
            "- {name: X, tier: S, source: none}\n- {name: X, tier: A, source: none}",
            "duplicate",
        ),
        ("name: X", "expected a list"),
    ],
)
def test_load_companies_rejects_invalid_entries(tmp_path, content, message):
    path = write(tmp_path, "companies.yaml", content)
    with pytest.raises(ConfigError, match=message):
        load_companies(path, SOURCES)


def test_load_companies_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_companies(tmp_path / "nope.yaml", SOURCES)


PROFILE = """
candidate_summary: Engineering student.
window_start: 2027-03-08
window_end: 2027-08-31
min_months: 4
ntfy_topic: secret-topic
"""


def test_load_profile_applies_defaults(tmp_path):
    profile = load_profile(write(tmp_path, "profile.yaml", PROFILE))
    assert profile.window_start == date(2027, 3, 8)
    assert profile.window_end == date(2027, 8, 31)
    assert profile.ntfy_server == "https://ntfy.sh"
    assert profile.llm_model == "haiku"
    assert profile.weights == Weights(0.5, 0.3, 0.2)
    assert profile.thresholds == Thresholds(7.5, 5.5)
    assert profile.adzuna_app_id is None


def test_load_profile_overrides_weights_and_thresholds(tmp_path):
    content = PROFILE + "weights: {tier: 0.6}\nthresholds: {immediate: 8}\n"
    profile = load_profile(write(tmp_path, "profile.yaml", content))
    assert profile.weights == Weights(0.6, 0.3, 0.2)
    assert profile.thresholds == Thresholds(8, 5.5)


@pytest.mark.parametrize(
    "content, message",
    [
        ("min_months: 4", "missing"),
        (PROFILE + "ntfy_toppic: typo\n", "unknown key"),
        (PROFILE + "weights: {tiers: 1}\n", "weights"),
        (PROFILE.replace("2027-08-31", "2027-01-01"), "window_start"),
        (PROFILE.replace("2027-03-08", "soon"), "date"),
    ],
)
def test_load_profile_rejects_invalid_content(tmp_path, content, message):
    with pytest.raises(ConfigError, match=message):
        load_profile(write(tmp_path, "profile.yaml", content))
