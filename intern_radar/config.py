"""Load and validate the YAML configuration files."""

from collections.abc import Collection
from dataclasses import dataclass, field, fields
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from intern_radar.models import TIERS, Company


class ConfigError(Exception):
    """A configuration file is missing or invalid."""


@dataclass(frozen=True)
class Weights:
    tier: float = 0.5
    relevance: float = 0.3
    dates: float = 0.2


@dataclass(frozen=True)
class Thresholds:
    immediate: float = 7.5
    digest: float = 5.5
    min_relevance: int = 6  # below this AI relevance an offer is never notified


@dataclass(frozen=True)
class Contact:
    name: str
    location: str
    phone: str
    email: str
    linkedin: str
    github: str


@dataclass(frozen=True)
class Profile:
    candidate_summary: str
    window_start: date
    window_end: date
    min_months: int
    telegram_token: str
    telegram_chat_id: int
    llm_model: str = "haiku"
    llm_effort: str | None = None
    max_llm_batches_per_run: int = 5
    max_immediate_per_run: int = 10
    adzuna_app_id: str | None = None
    adzuna_app_key: str | None = None
    weights: Weights = field(default_factory=Weights)
    thresholds: Thresholds = field(default_factory=Thresholds)
    cv_url: str | None = None
    letters_email: str | None = None
    smtp_app_password: str | None = None
    letter_model: str = "sonnet"
    letter_effort: str | None = "low"
    max_letters_per_day: int = 10
    contact: Contact | None = None


REQUIRED_PROFILE_KEYS = (
    "candidate_summary",
    "window_start",
    "window_end",
    "min_months",
    "telegram_token",
    "telegram_chat_id",
)


def _read_yaml(path: Path) -> Any:
    if not path.exists():
        raise ConfigError(f"{path} not found")
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML ({exc})") from exc


def load_companies(path: Path, known_sources: Collection[str]) -> list[Company]:
    data = _read_yaml(path)
    if not isinstance(data, list):
        raise ConfigError(f"{path}: expected a list of companies")
    companies: list[Company] = []
    names: set[str] = set()
    for index, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: entry {index} is not a mapping")
        missing = sorted({"name", "tier", "source"} - entry.keys())
        if missing:
            raise ConfigError(f"{path}: entry {index} is missing {missing}")
        name = str(entry["name"])
        if entry["tier"] not in TIERS:
            raise ConfigError(f"{path}: {name}: invalid tier {entry['tier']!r}")
        if entry["source"] not in known_sources:
            raise ConfigError(f"{path}: {name}: unknown source {entry['source']!r}")
        if name in names:
            raise ConfigError(f"{path}: duplicate company {name!r}")
        names.add(name)
        params = {
            key: value
            for key, value in entry.items()
            if key not in ("name", "tier", "source")
        }
        companies.append(Company(name, entry["tier"], entry["source"], params))
    return companies


def _build(cls: type, values: Any, label: str) -> Any:
    if not isinstance(values, dict):
        raise ConfigError(f"profile: {label} must be a mapping")
    try:
        return cls(**values)
    except TypeError as exc:
        raise ConfigError(f"profile: invalid {label} ({exc})") from exc


def load_profile(path: Path) -> Profile:
    data = _read_yaml(path)
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a mapping")
    missing = [key for key in REQUIRED_PROFILE_KEYS if key not in data]
    if missing:
        raise ConfigError(f"{path}: missing {missing}")
    allowed = {f.name for f in fields(Profile)}
    unknown = sorted(data.keys() - allowed)
    if unknown:
        raise ConfigError(f"{path}: unknown key(s) {unknown}")
    for key in ("window_start", "window_end"):
        if not isinstance(data[key], date):
            raise ConfigError(f"{path}: {key} must be a date (YYYY-MM-DD)")
    if data["window_start"] >= data["window_end"]:
        raise ConfigError(f"{path}: window_start must be before window_end")
    if not isinstance(data["telegram_chat_id"], int):
        raise ConfigError(f"{path}: telegram_chat_id must be an integer")
    values = dict(data)
    values["weights"] = _build(Weights, data.get("weights", {}), "weights")
    values["thresholds"] = _build(Thresholds, data.get("thresholds", {}), "thresholds")
    if "contact" in data:
        values["contact"] = _build(Contact, data["contact"], "contact")
    return Profile(**values)
