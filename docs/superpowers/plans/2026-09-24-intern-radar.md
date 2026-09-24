# intern-radar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python CLI that watches the career pages of top AI/tech companies for internships, scores them against the candidate profile with `claude -p`, and pushes the relevant ones through ntfy.

**Architecture:** Source plugins fetch internship-titled jobs from public ATS APIs (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Workday), two custom portals (Amazon, Microsoft) and Adzuna. A pipeline deduplicates them in SQLite, applies a rule-based pre-filter, scores new candidates in batches through the `claude` CLI with a JSON schema, computes a deterministic final score, and sends ntfy notifications (immediate + evening digest). systemd timers run it on the VPS.

**Tech Stack:** Python ≥ 3.12, Poetry, httpx, Typer, PyYAML, sqlite3 (stdlib), pytest, ruff, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-24-intern-radar-design.md`

## Global Constraints

- Internship window 2027-03-08 → 2027-08-31, minimum 4 months (values live in `config/profile.yaml`, never hard-coded).
- Final score: `0.5 * tier_points + 0.3 * ai_relevance + 0.2 * dates_points`; tier_points S=10, A=8, B=6, unlisted=4; dates_points fits=10, unknown=6, too_short_extendable=4; −2 if `local_students_only`; hard exclusions: not an internship, `dates_fit = incompatible`, `phd_only`, `language_ok = false`.
- Thresholds: ≥ 7.5 immediate, 5.5 ≤ score < 7.5 digest, below 5.5 stored only (configurable).
- LLM calls only through `claude -p --model haiku --output-format json --json-schema …`, batches of ≤ 10 jobs, descriptions truncated to 3,000 characters.
- ntfy target: `https://ntfy.sh/<secret topic>`; the topic is only in `config/profile.yaml`.
- `config/profile.yaml`, `data/`, `logs/` are never committed.
- HTTP: 20 s timeout, ≥ 1 s between two requests to the same host, User-Agent `intern-radar/0.1 (+https://github.com/rmouahid/intern-radar)`.
- Git: Conventional Commits in English, Git Flow (`main`, `develop`, `feature/<issue>-<desc>`), rebase merges, no attribution trailer or AI mention in any commit, PR or issue.
- Code, comments, docs and commit messages in English.

## Deviations from the spec (decided while planning)

- **Plugins return only internship-titled jobs** (title regex from `prefilter.is_internship_title`) and skip ids already in the store. This keeps SQLite small and avoids thousands of detail requests. The pipeline still applies the full pre-filter.
- **Test fixtures are minimal inline payloads** that mirror the real response shapes observed on 2026-09-24, instead of full recorded dumps (smaller, readable, deterministic).
- **systemd timers instead of cron + flock**: the VPS runs in UTC and Ubuntu cron has no reliable per-job time zone; `OnCalendar=… Europe/Paris` handles DST, and a oneshot service never runs twice concurrently.
- **Dry runs use an in-memory database** so they never mark real offers as notified.
- **Adzuna jobs duplicating an ATS job** (same company, same title) are stored as `duplicate` and never notified.

## Review Focus

1. **Multi-location postings including France** ("Paris, France; London, UK") must pass the pre-filter; only France-only postings are dropped → `tests/test_prefilter.py::test_multi_location_with_non_french_office_passes` (Task 4).
2. **Quota exhaustion must not burn retries**: an `LLMError` leaves jobs pending without incrementing `attempts`; only jobs missing from a successful answer count an attempt → `tests/test_pipeline.py::test_llm_failure_keeps_jobs_pending_without_attempt` (Task 9).
3. **First run flood**: the first run discovers every open internship at once; LLM batches per run and immediate notifications per run are capped, the rest carries over → `tests/test_pipeline.py::test_caps_llm_batches_and_immediate_notifications` (Task 9).
4. **LLM returns malformed or partial items** (unknown enum, string booleans, missing job) → those jobs stay pending, the others are saved → `tests/test_scorer.py::test_invalid_items_are_skipped` (Task 7).
5. **Long digests**: more than 20 digest offers must stay under ntfy's 4 KB limit → `tests/test_notifier.py::test_digest_is_truncated_after_20_lines` (Task 8).

---

## Milestones, issues and branches

Each milestone is one GitHub issue, one `feature/*` branch from `develop`, one PR (rebase merge). Issue numbers are assigned in Task 0; replace `<n>` accordingly.

| Milestone | Tasks | Branch |
|---|---|---|
| 1. Skeleton | 1–3 | `feature/<n>-skeleton` |
| 2. ATS plugins + pre-filter | 4–6 | `feature/<n>-ats-sources` |
| 3. Scoring | 7 | `feature/<n>-scoring` |
| 4. Notifications + CLI | 8–10 | `feature/<n>-notifications-cli` |
| 5. Big-tech portals + Adzuna | 11–12 | `feature/<n>-portals-adzuna` |
| 6. Company list + deployment | 13–14 | `feature/<n>-deployment` |

---

### Task 0: Repository setup

**Files:** none (git and GitHub only)

- [ ] **Step 1: Integrate the design branch into `develop`**

```bash
cd /root/remote-claude/intern-radar
git switch develop
git merge --ff-only feature/design-spec
git branch -d feature/design-spec
git add docs/superpowers/plans/2026-09-24-intern-radar.md
git switch -c feature/plan && git commit -m "docs: add implementation plan" && git switch develop && git merge --ff-only feature/plan && git branch -d feature/plan
```

- [ ] **Step 2: Create the public GitHub repo and push `main` and `develop`**

```bash
gh repo create rmouahid/intern-radar --public --description "Watches top AI/tech career pages for internships, scores them with an LLM and notifies through ntfy" --source . --remote origin
git push -u origin main develop
gh repo edit rmouahid/intern-radar --default-branch develop
```

- [ ] **Step 3: Create one issue per milestone**

```bash
gh issue create -R rmouahid/intern-radar -t "Project skeleton: models, config, store, CI" -b "Milestone 1 of docs/superpowers/plans/2026-09-24-intern-radar.md (tasks 1-3)."
gh issue create -R rmouahid/intern-radar -t "ATS source plugins and pre-filter" -b "Milestone 2 (tasks 4-6): Greenhouse, Lever, Ashby, Workable, SmartRecruiters, pre-filter, ranking."
gh issue create -R rmouahid/intern-radar -t "LLM scoring through the claude CLI" -b "Milestone 3 (task 7)."
gh issue create -R rmouahid/intern-radar -t "ntfy notifications, pipeline and CLI" -b "Milestone 4 (tasks 8-10)."
gh issue create -R rmouahid/intern-radar -t "Workday, Amazon, Microsoft and Adzuna sources" -b "Milestone 5 (tasks 11-12)."
gh issue create -R rmouahid/intern-radar -t "Verified company list and VPS deployment" -b "Milestone 6 (tasks 13-14)."
```

Expected: issues #1 to #6. Start milestone 1: `git switch -c feature/1-skeleton develop`.

---

### Task 1: Poetry project, package, CI

**Files:**
- Create: `pyproject.toml`, `LICENSE`, `intern_radar/__init__.py`, `tests/__init__.py`, `tests/test_smoke.py`, `.github/workflows/tests.yml`

**Interfaces:**
- Produces: installable package `intern_radar`, console script `intern-radar = intern_radar.cli:app` (module created in Task 10; the entry point is declared now).

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[tool.poetry]
name = "intern-radar"
version = "0.1.0"
description = "Watches top AI/tech career pages for internships, scores them with an LLM and notifies through ntfy"
authors = ["rmouahid"]
license = "MIT"
readme = "README.md"
packages = [{ include = "intern_radar" }]

[tool.poetry.dependencies]
python = "^3.12"

[tool.poetry.scripts]
intern-radar = "intern_radar.cli:app"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]

[tool.ruff]
line-length = 88
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

- [ ] **Step 2: Add dependencies**

```bash
poetry add httpx typer pyyaml
poetry add --group dev pytest ruff
```

Expected: `poetry.lock` created, the three runtime and two dev dependencies listed in `pyproject.toml`.

- [ ] **Step 3: Package files, license, smoke test**

`intern_radar/__init__.py`:

```python
"""Watch top AI/tech companies for internship offers."""

__version__ = "0.1.0"
```

`tests/__init__.py`: empty file.

`LICENSE`: MIT license text, first lines `MIT License` / blank / `Copyright (c) 2026 rmouahid` (same as `doc-centralizer/LICENSE`).

`tests/test_smoke.py`:

```python
import intern_radar


def test_package_exposes_version():
    assert intern_radar.__version__ == "0.1.0"
```

- [ ] **Step 4: Run tests and lint**

Run: `poetry run pytest -q && poetry run ruff check . && poetry run ruff format --check .`
Expected: `1 passed`, ruff reports no issue.

- [ ] **Step 5: CI workflow**

`.github/workflows/tests.yml`:

```yaml
name: Tests

on:
  push:
    branches: [main, develop]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install Poetry
        run: pip install --no-cache-dir poetry

      - name: Cache Poetry dependencies
        uses: actions/cache@v4
        with:
          path: ~/.cache/pypoetry
          key: poetry-${{ runner.os }}-${{ hashFiles('poetry.lock') }}

      - name: Install dependencies
        run: poetry install --no-interaction --no-ansi

      - name: Lint
        run: poetry run ruff check . && poetry run ruff format --check .

      - name: Run tests
        run: poetry run pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml poetry.lock LICENSE intern_radar tests .github
git commit -m "build: set up poetry project, ruff and CI"
```

---

### Task 2: Domain models and configuration loading

**Files:**
- Create: `intern_radar/models.py`, `intern_radar/config.py`, `config/profile.example.yaml`, `config/companies.yaml` (initial 3 entries), `tests/factories.py`, `tests/test_config.py`

**Interfaces:**
- Produces:
  - `models.Tier`, `models.DatesFit`, `models.Eligibility` (Literal types); `models.TIERS`, `models.DATES_FIT_VALUES`, `models.ELIGIBILITY_VALUES` (tuples)
  - `models.Company(name: str, tier: Tier, source: str, params: dict[str, Any])`
  - `models.Job(id, company, tier, title, location, url, description, source, posted_at: str | None = None)`
  - `models.Assessment(is_internship: bool, ai_relevance: int, dates_fit: DatesFit, eligibility: Eligibility, visa_note: str, language_ok: bool, summary: str)`
  - `models.ScoredJob(job: Job, assessment: Assessment, score: float | None)`
  - `config.ConfigError`, `config.Weights(tier=0.5, relevance=0.3, dates=0.2)`, `config.Thresholds(immediate=7.5, digest=5.5)`, `config.Profile(...)` (fields below)
  - `config.load_companies(path: Path, known_sources: Collection[str]) -> list[Company]`
  - `config.load_profile(path: Path) -> Profile`
  - `tests/factories.py`: `make_job(**overrides) -> Job`, `make_assessment(**overrides) -> Assessment`, `make_profile(**overrides) -> Profile`

- [ ] **Step 1: Write `intern_radar/models.py`**

```python
"""Domain objects shared by every module."""

from dataclasses import dataclass, field
from typing import Any, Literal

Tier = Literal["S", "A", "B", "unlisted"]
DatesFit = Literal["fits", "too_short_extendable", "incompatible", "unknown"]
Eligibility = Literal["ok", "phd_only", "local_students_only", "unknown"]

TIERS: tuple[str, ...] = ("S", "A", "B", "unlisted")
DATES_FIT_VALUES: tuple[str, ...] = (
    "fits",
    "too_short_extendable",
    "incompatible",
    "unknown",
)
ELIGIBILITY_VALUES: tuple[str, ...] = (
    "ok",
    "phd_only",
    "local_students_only",
    "unknown",
)


@dataclass(frozen=True)
class Company:
    """A watched company and how to reach its job feed."""

    name: str
    tier: Tier
    source: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Job:
    """A job posting normalized across every source."""

    id: str
    company: str
    tier: Tier
    title: str
    location: str
    url: str
    description: str
    source: str
    posted_at: str | None = None


@dataclass(frozen=True)
class Assessment:
    """What the LLM says about one job."""

    is_internship: bool
    ai_relevance: int
    dates_fit: DatesFit
    eligibility: Eligibility
    visa_note: str
    language_ok: bool
    summary: str


@dataclass(frozen=True)
class ScoredJob:
    """A job with its assessment; `score` is None when the job is excluded."""

    job: Job
    assessment: Assessment
    score: float | None
```

- [ ] **Step 2: Write `tests/factories.py`**

```python
"""Builders for test objects with sensible defaults."""

from datetime import date
from typing import Any

from intern_radar.config import Profile
from intern_radar.models import Assessment, Job


def make_job(**overrides: Any) -> Job:
    values: dict[str, Any] = {
        "id": "greenhouse:acme:1",
        "company": "Acme",
        "tier": "A",
        "title": "Machine Learning Intern",
        "location": "London, UK",
        "url": "https://example.com/jobs/1",
        "description": "Build ML systems.",
        "source": "greenhouse",
        "posted_at": "2026-09-20",
    }
    values.update(overrides)
    return Job(**values)


def make_assessment(**overrides: Any) -> Assessment:
    values: dict[str, Any] = {
        "is_internship": True,
        "ai_relevance": 8,
        "dates_fit": "fits",
        "eligibility": "ok",
        "visa_note": "UK: GAE scheme via a sponsor",
        "language_ok": True,
        "summary": "Applied ML on LLM agents.",
    }
    values.update(overrides)
    return Assessment(**values)


def make_profile(**overrides: Any) -> Profile:
    values: dict[str, Any] = {
        "candidate_summary": "Engineering student, RAG and LLM projects.",
        "window_start": date(2027, 3, 8),
        "window_end": date(2027, 8, 31),
        "min_months": 4,
        "ntfy_topic": "test-topic",
    }
    values.update(overrides)
    return Profile(**values)
```

- [ ] **Step 3: Write the failing tests `tests/test_config.py`**

```python
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
        ("- {name: X, tier: S, source: none}\n- {name: X, tier: A, source: none}",
         "duplicate"),
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
```

- [ ] **Step 4: Run the tests to see them fail**

Run: `poetry run pytest tests/test_config.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'intern_radar.config'`.

- [ ] **Step 5: Write `intern_radar/config.py`**

```python
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


@dataclass(frozen=True)
class Profile:
    candidate_summary: str
    window_start: date
    window_end: date
    min_months: int
    ntfy_topic: str
    ntfy_server: str = "https://ntfy.sh"
    llm_model: str = "haiku"
    max_llm_batches_per_run: int = 5
    max_immediate_per_run: int = 10
    adzuna_app_id: str | None = None
    adzuna_app_key: str | None = None
    weights: Weights = field(default_factory=Weights)
    thresholds: Thresholds = field(default_factory=Thresholds)


REQUIRED_PROFILE_KEYS = (
    "candidate_summary",
    "window_start",
    "window_end",
    "min_months",
    "ntfy_topic",
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
    values = dict(data)
    values["weights"] = _build(Weights, data.get("weights", {}), "weights")
    values["thresholds"] = _build(Thresholds, data.get("thresholds", {}), "thresholds")
    return Profile(**values)
```

- [ ] **Step 6: Run the tests to see them pass**

Run: `poetry run pytest tests/test_config.py -q`
Expected: all pass.

- [ ] **Step 7: Example profile and first companies**

`config/profile.example.yaml`:

```yaml
# Copy to config/profile.yaml (gitignored) and fill in.
candidate_summary: |
  Computer engineering student (CY Tech, France). Built a RAG agent and a
  vector search engine from scratch in Python, a local LLM documentation
  assistant (llama.cpp, FAISS), an MCP server, and a PySpark streaming
  pipeline. Previous internship: deployed a self-hosted RAG agent (Docker).
  Skills: Python, NumPy, FastAPI, Docker, PySpark, Java, SQL.
  Languages: French (native), English (C2), Spanish (B2).
  Looking for an AI / ML engineering internship.
window_start: 2027-03-08
window_end: 2027-08-31
min_months: 4
ntfy_topic: intern-radar-CHANGE-ME-to-a-long-random-string
# ntfy_server: https://ntfy.sh
# llm_model: haiku
# max_llm_batches_per_run: 5
# max_immediate_per_run: 10
# adzuna_app_id: your-app-id      # free account on developer.adzuna.com
# adzuna_app_key: your-app-key
# weights: {tier: 0.5, relevance: 0.3, dates: 0.2}
# thresholds: {immediate: 7.5, digest: 5.5}
```

`config/companies.yaml` (completed in Task 13):

```yaml
- name: Anthropic
  tier: S
  source: greenhouse
  board: anthropic
- name: OpenAI
  tier: S
  source: ashby
  org: openai
- name: Palantir
  tier: A
  source: lever
  site: palantir
```

- [ ] **Step 8: Commit**

```bash
git add intern_radar/models.py intern_radar/config.py config tests/factories.py tests/test_config.py
git commit -m "feat: add domain models and YAML configuration loading"
```

---

### Task 3: SQLite store

**Files:**
- Create: `intern_radar/store.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: `models.Job`, `models.Assessment`, `models.ScoredJob`
- Produces: `store.Store(path: str)` with methods
  - `close() -> None`
  - `known_ids() -> set[str]`
  - `add(job: Job, status: str, now: datetime) -> None` — status is `"pending"`, `"rejected"` or `"duplicate"`; description stored only for pending
  - `has_similar(company: str, title: str) -> bool` — a non-Adzuna job with same company and case-insensitive title exists
  - `pending(limit: int | None = None) -> list[Job]` — status pending and `attempts < MAX_ATTEMPTS` (3), oldest first
  - `record_attempt(job_ids: list[str]) -> None`
  - `save_assessment(job_id: str, assessment: Assessment, score: float | None) -> None`
  - `due_immediate(threshold: float, limit: int) -> list[ScoredJob]`
  - `mark_notified(job_id: str, now: datetime) -> None`
  - `due_digest(low: float, high: float) -> list[ScoredJob]`
  - `mark_digested(job_ids: list[str], now: datetime) -> None`
  - `scored(min_score: float) -> list[ScoredJob]`
  - `record_source_result(company: str, error: str | None, now: datetime) -> None`
  - `sources_to_alert(now: datetime, after: timedelta) -> list[tuple[str, str]]`
  - `mark_source_alerted(company: str) -> None`
  - `record_llm_result(ok: bool, now: datetime) -> None`
  - `llm_alert_due(now: datetime, after: timedelta) -> bool`
  - `mark_llm_alerted() -> None`

- [ ] **Step 1: Write the failing tests `tests/test_store.py`**

```python
from datetime import UTC, datetime, timedelta

import pytest

from intern_radar.store import Store
from tests.factories import make_assessment, make_job

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def test_add_and_known_ids(store):
    store.add(make_job(id="a"), "pending", NOW)
    store.add(make_job(id="b"), "rejected", NOW)
    assert store.known_ids() == {"a", "b"}


def test_add_is_idempotent(store):
    store.add(make_job(id="a", title="First"), "pending", NOW)
    store.add(make_job(id="a", title="Second"), "pending", NOW)
    assert [job.title for job in store.pending()] == ["First"]


def test_pending_returns_only_pending_jobs_with_description(store):
    store.add(make_job(id="a", description="full text"), "pending", NOW)
    store.add(make_job(id="b"), "rejected", NOW)
    assert store.pending() == [make_job(id="a", description="full text")]


def test_rejected_jobs_do_not_keep_their_description(store):
    store.add(make_job(id="b", description="long"), "rejected", NOW)
    row = store._db.execute("SELECT description FROM jobs WHERE id='b'").fetchone()
    assert row["description"] == ""


def test_pending_respects_limit_and_attempts(store):
    for job_id in ("a", "b", "c"):
        store.add(make_job(id=job_id), "pending", NOW)
    for _ in range(3):
        store.record_attempt(["a"])
    assert [job.id for job in store.pending()] == ["b", "c"]
    assert [job.id for job in store.pending(limit=1)] == ["b"]


def test_has_similar_ignores_case_and_adzuna_jobs(store):
    store.add(make_job(id="gh:1", company="Stripe", title="ML Intern"), "pending", NOW)
    store.add(
        make_job(id="adzuna:9", company="Google", title="AI Intern", source="adzuna"),
        "pending",
        NOW,
    )
    assert store.has_similar("Stripe", "ml intern")
    assert not store.has_similar("Stripe", "Data Intern")
    assert not store.has_similar("Google", "AI Intern")


def test_scored_jobs_flow_through_immediate_and_digest(store):
    for job_id, score in (("hi", 9.0), ("mid", 6.0), ("low", 4.0), ("ex", None)):
        store.add(make_job(id=job_id), "pending", NOW)
        store.save_assessment(job_id, make_assessment(), score)

    assert store.pending() == []
    assert [s.job.id for s in store.due_immediate(7.5, limit=10)] == ["hi"]
    store.mark_notified("hi", NOW)
    assert store.due_immediate(7.5, limit=10) == []

    digest = store.due_digest(5.5, 7.5)
    assert [(s.job.id, s.score) for s in digest] == [("mid", 6.0)]
    assert digest[0].assessment == make_assessment()
    store.mark_digested(["mid"], NOW)
    assert store.due_digest(5.5, 7.5) == []

    assert [s.job.id for s in store.scored(min_score=5)] == ["hi", "mid"]


def test_due_immediate_orders_by_score_and_limits(store):
    for job_id, score in (("a", 8.0), ("b", 9.5), ("c", 7.6)):
        store.add(make_job(id=job_id), "pending", NOW)
        store.save_assessment(job_id, make_assessment(), score)
    assert [s.job.id for s in store.due_immediate(7.5, limit=2)] == ["b", "a"]


def test_source_alert_after_three_days_of_failures(store):
    store.record_source_result("Acme", "HTTP 500", NOW)
    store.record_source_result("Acme", "HTTP 503", NOW + timedelta(days=2))
    assert store.sources_to_alert(NOW + timedelta(days=2), timedelta(days=3)) == []
    later = NOW + timedelta(days=3)
    assert store.sources_to_alert(later, timedelta(days=3)) == [("Acme", "HTTP 503")]
    store.mark_source_alerted("Acme")
    assert store.sources_to_alert(later, timedelta(days=3)) == []


def test_source_success_resets_the_failure_streak(store):
    store.record_source_result("Acme", "HTTP 500", NOW)
    store.record_source_result("Acme", None, NOW + timedelta(days=1))
    store.record_source_result("Acme", "HTTP 500", NOW + timedelta(days=2))
    assert store.sources_to_alert(NOW + timedelta(days=4), timedelta(days=3)) == []


def test_llm_alert_after_a_day_of_failures(store):
    store.record_llm_result(False, NOW)
    assert not store.llm_alert_due(NOW + timedelta(hours=23), timedelta(days=1))
    assert store.llm_alert_due(NOW + timedelta(days=1), timedelta(days=1))
    store.mark_llm_alerted()
    assert not store.llm_alert_due(NOW + timedelta(days=2), timedelta(days=1))
    store.record_llm_result(True, NOW + timedelta(days=2))
    store.record_llm_result(False, NOW + timedelta(days=3))
    assert not store.llm_alert_due(NOW + timedelta(days=3), timedelta(days=1))
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `poetry run pytest tests/test_store.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'intern_radar.store'`.

- [ ] **Step 3: Write `intern_radar/store.py`**

```python
"""SQLite persistence: seen jobs, assessments, notification and health state."""

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timedelta

from intern_radar.models import Assessment, Job, ScoredJob

MAX_ATTEMPTS = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    company TEXT NOT NULL,
    tier TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT NOT NULL,
    url TEXT NOT NULL,
    description TEXT NOT NULL,
    source TEXT NOT NULL,
    posted_at TEXT,
    first_seen TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    assessment TEXT,
    score REAL,
    notified_at TEXT,
    digested_at TEXT
);
CREATE TABLE IF NOT EXISTS source_health (
    company TEXT PRIMARY KEY,
    first_failure TEXT NOT NULL,
    last_error TEXT NOT NULL,
    alerted INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS llm_health (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    first_failure TEXT NOT NULL,
    alerted INTEGER NOT NULL DEFAULT 0
);
"""

JOB_COLUMNS = (
    "id",
    "company",
    "tier",
    "title",
    "location",
    "url",
    "description",
    "source",
    "posted_at",
)


def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(**{column: row[column] for column in JOB_COLUMNS})


def _row_to_scored(row: sqlite3.Row) -> ScoredJob:
    assessment = Assessment(**json.loads(row["assessment"]))
    return ScoredJob(_row_to_job(row), assessment, row["score"])


class Store:
    def __init__(self, path: str) -> None:
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    # --- jobs -------------------------------------------------------------

    def known_ids(self) -> set[str]:
        return {row["id"] for row in self._db.execute("SELECT id FROM jobs")}

    def add(self, job: Job, status: str, now: datetime) -> None:
        values = [getattr(job, column) for column in JOB_COLUMNS]
        if status != "pending":
            values[JOB_COLUMNS.index("description")] = ""
        with self._db:
            self._db.execute(
                f"INSERT OR IGNORE INTO jobs ({', '.join(JOB_COLUMNS)}, first_seen,"
                f" status) VALUES ({', '.join('?' * (len(JOB_COLUMNS) + 2))})",
                [*values, now.isoformat(), status],
            )

    def has_similar(self, company: str, title: str) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM jobs WHERE company = ? AND lower(title) = lower(?)"
            " AND source != 'adzuna' LIMIT 1",
            (company, title),
        ).fetchone()
        return row is not None

    def pending(self, limit: int | None = None) -> list[Job]:
        sql = (
            "SELECT * FROM jobs WHERE status = 'pending' AND attempts < ?"
            " ORDER BY first_seen, id"
        )
        params: list[object] = [MAX_ATTEMPTS]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return [_row_to_job(row) for row in self._db.execute(sql, params)]

    def record_attempt(self, job_ids: list[str]) -> None:
        with self._db:
            self._db.executemany(
                "UPDATE jobs SET attempts = attempts + 1 WHERE id = ?",
                [(job_id,) for job_id in job_ids],
            )

    def save_assessment(
        self, job_id: str, assessment: Assessment, score: float | None
    ) -> None:
        with self._db:
            self._db.execute(
                "UPDATE jobs SET status = 'scored', assessment = ?, score = ?"
                " WHERE id = ?",
                (json.dumps(asdict(assessment)), score, job_id),
            )

    def due_immediate(self, threshold: float, limit: int) -> list[ScoredJob]:
        rows = self._db.execute(
            "SELECT * FROM jobs WHERE status = 'scored' AND score >= ?"
            " AND notified_at IS NULL ORDER BY score DESC, id LIMIT ?",
            (threshold, limit),
        )
        return [_row_to_scored(row) for row in rows]

    def mark_notified(self, job_id: str, now: datetime) -> None:
        with self._db:
            self._db.execute(
                "UPDATE jobs SET notified_at = ? WHERE id = ?",
                (now.isoformat(), job_id),
            )

    def due_digest(self, low: float, high: float) -> list[ScoredJob]:
        rows = self._db.execute(
            "SELECT * FROM jobs WHERE status = 'scored' AND score >= ?"
            " AND score < ? AND digested_at IS NULL ORDER BY score DESC, id",
            (low, high),
        )
        return [_row_to_scored(row) for row in rows]

    def mark_digested(self, job_ids: list[str], now: datetime) -> None:
        with self._db:
            self._db.executemany(
                "UPDATE jobs SET digested_at = ? WHERE id = ?",
                [(now.isoformat(), job_id) for job_id in job_ids],
            )

    def scored(self, min_score: float) -> list[ScoredJob]:
        rows = self._db.execute(
            "SELECT * FROM jobs WHERE status = 'scored' AND score >= ?"
            " ORDER BY score DESC, id",
            (min_score,),
        )
        return [_row_to_scored(row) for row in rows]

    # --- health -----------------------------------------------------------

    def record_source_result(
        self, company: str, error: str | None, now: datetime
    ) -> None:
        with self._db:
            if error is None:
                self._db.execute(
                    "DELETE FROM source_health WHERE company = ?", (company,)
                )
            else:
                self._db.execute(
                    "INSERT INTO source_health (company, first_failure, last_error)"
                    " VALUES (?, ?, ?) ON CONFLICT(company)"
                    " DO UPDATE SET last_error = excluded.last_error",
                    (company, now.isoformat(), error),
                )

    def sources_to_alert(
        self, now: datetime, after: timedelta
    ) -> list[tuple[str, str]]:
        rows = self._db.execute(
            "SELECT company, first_failure, last_error FROM source_health"
            " WHERE alerted = 0 ORDER BY company"
        )
        return [
            (row["company"], row["last_error"])
            for row in rows
            if now - datetime.fromisoformat(row["first_failure"]) >= after
        ]

    def mark_source_alerted(self, company: str) -> None:
        with self._db:
            self._db.execute(
                "UPDATE source_health SET alerted = 1 WHERE company = ?", (company,)
            )

    def record_llm_result(self, ok: bool, now: datetime) -> None:
        with self._db:
            if ok:
                self._db.execute("DELETE FROM llm_health")
            else:
                self._db.execute(
                    "INSERT OR IGNORE INTO llm_health (id, first_failure)"
                    " VALUES (1, ?)",
                    (now.isoformat(),),
                )

    def llm_alert_due(self, now: datetime, after: timedelta) -> bool:
        row = self._db.execute(
            "SELECT first_failure, alerted FROM llm_health WHERE id = 1"
        ).fetchone()
        if row is None or row["alerted"]:
            return False
        return now - datetime.fromisoformat(row["first_failure"]) >= after

    def mark_llm_alerted(self) -> None:
        with self._db:
            self._db.execute("UPDATE llm_health SET alerted = 1")
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `poetry run pytest tests/test_store.py -q`
Expected: all pass.

- [ ] **Step 5: Lint and commit**

```bash
poetry run ruff check . && poetry run ruff format .
git add intern_radar/store.py tests/test_store.py
git commit -m "feat: add SQLite store for jobs, scores and source health"
```

- [ ] **Step 6: Open the milestone 1 PR**

```bash
git fetch origin && git rebase origin/develop && poetry run pytest -q
git push -u origin feature/1-skeleton
gh pr create --base develop --title "feat: project skeleton with models, config and store" --body "Milestone 1 of the implementation plan: Poetry project and CI, domain models, YAML configuration loading, SQLite store.

Tests: \`poetry run pytest -q\` passes locally.

Closes #1"
```

Wait for CI to pass; the user merges (`gh pr merge --rebase --delete-branch`). Then `git switch develop && git pull --ff-only && git switch -c feature/2-ats-sources`.

---

### Task 4: Pre-filter and ranking

**Files:**
- Create: `intern_radar/prefilter.py`, `intern_radar/ranking.py`, `tests/test_prefilter.py`, `tests/test_ranking.py`

**Interfaces:**
- Consumes: `models.Job`, `models.Assessment`, `config.Weights`
- Produces:
  - `prefilter.is_internship_title(title: str) -> bool`
  - `prefilter.is_france_only(location: str) -> bool`
  - `prefilter.passes(job: Job) -> bool`
  - `ranking.is_excluded(assessment: Assessment) -> bool`
  - `ranking.final_score(tier: Tier, assessment: Assessment, weights: Weights) -> float | None`

- [ ] **Step 1: Write the failing tests `tests/test_prefilter.py`**

```python
import pytest

from intern_radar.prefilter import is_france_only, is_internship_title, passes
from tests.factories import make_job


@pytest.mark.parametrize(
    "title",
    [
        "Machine Learning Intern",
        "Software Engineering Interns",
        "Research Internship (Summer 2027)",
        "ML Intern/Co-op (Winter 2027)",
        "AI Coop",
        "Stagiaire Data Science",
        "Graduate Trainee - AI",
        "Industrial Placement, Machine Learning",
        "2027 Intern - Machine Learning Engineer",
    ],
)
def test_internship_titles_match(title):
    assert is_internship_title(title)


@pytest.mark.parametrize(
    "title",
    [
        "Senior Full-Stack Engineer, Internal Applications",
        "Director, US International Tax",
        "Internal Communications Manager",
        "Machine Learning Engineer",
        "",
    ],
)
def test_other_titles_do_not_match(title):
    assert not is_internship_title(title)


@pytest.mark.parametrize(
    "location, expected",
    [
        ("Paris, France", True),
        ("Remote - France", True),
        ("Sophia Antipolis", True),
        ("London, UK", False),
        ("", False),
        ("Remote", False),
        ("Toronto, Ontario", False),
    ],
)
def test_is_france_only(location, expected):
    assert is_france_only(location) is expected


def test_multi_location_with_non_french_office_passes():
    assert not is_france_only("Paris, France; London, UK")
    assert not is_france_only("Paris, France | Zurich, Switzerland")
    assert not is_france_only("Paris or Dublin")
    assert is_france_only("Paris, France; Lyon, France")


def test_passes_combines_title_and_location():
    assert passes(make_job(title="AI Intern", location="London, UK"))
    assert not passes(make_job(title="AI Intern", location="Paris, France"))
    assert not passes(make_job(title="AI Engineer", location="London, UK"))
```

- [ ] **Step 2: Write the failing tests `tests/test_ranking.py`**

```python
import pytest

from intern_radar.config import Weights
from intern_radar.ranking import final_score, is_excluded
from tests.factories import make_assessment

W = Weights()


@pytest.mark.parametrize(
    "overrides",
    [
        {"is_internship": False},
        {"dates_fit": "incompatible"},
        {"eligibility": "phd_only"},
        {"language_ok": False},
    ],
)
def test_hard_exclusions(overrides):
    assessment = make_assessment(**overrides)
    assert is_excluded(assessment)
    assert final_score("S", assessment, W) is None


def test_spec_examples():
    google = make_assessment(ai_relevance=9, dates_fit="fits")
    stripe = make_assessment(ai_relevance=4, dates_fit="unknown")
    unlisted = make_assessment(ai_relevance=9, dates_fit="unknown")
    assert final_score("S", google, W) == pytest.approx(9.7)
    assert final_score("A", stripe, W) == pytest.approx(6.4)
    assert final_score("unlisted", unlisted, W) == pytest.approx(5.9)


def test_short_internship_and_local_students_penalty():
    short = make_assessment(ai_relevance=10, dates_fit="too_short_extendable")
    assert final_score("S", short, W) == pytest.approx(8.8)
    local = make_assessment(ai_relevance=10, eligibility="local_students_only")
    assert final_score("S", local, W) == pytest.approx(8.0)


def test_score_never_goes_below_zero():
    weak = make_assessment(
        ai_relevance=0, dates_fit="too_short_extendable",
        eligibility="local_students_only",
    )
    assert final_score("unlisted", weak, Weights(0, 0, 0)) == 0.0


def test_custom_weights():
    assessment = make_assessment(ai_relevance=5, dates_fit="fits")
    assert final_score("B", assessment, Weights(1, 0, 0)) == pytest.approx(6.0)
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `poetry run pytest tests/test_prefilter.py tests/test_ranking.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Write `intern_radar/prefilter.py`**

```python
"""Cheap rule-based filter applied before any LLM call."""

import re

from intern_radar.models import Job

TITLE_RE = re.compile(
    r"\b(interns?|internships?|co-?ops?|stagiaires?|trainees?|placements?)\b",
    re.IGNORECASE,
)
FRANCE_RE = re.compile(
    r"\b(france|paris|lyon|marseille|toulouse|nice|nantes|strasbourg|montpellier"
    r"|bordeaux|lille|rennes|grenoble|sophia[- ]antipolis)\b",
    re.IGNORECASE,
)
LOCATION_SEPARATOR_RE = re.compile(r"\s*(?:;|\||/|\bor\b)\s*", re.IGNORECASE)


def is_internship_title(title: str) -> bool:
    return bool(TITLE_RE.search(title))


def is_france_only(location: str) -> bool:
    """True when every listed location is in France."""
    segments = [s for s in LOCATION_SEPARATOR_RE.split(location) if s.strip()]
    return bool(segments) and all(FRANCE_RE.search(s) for s in segments)


def passes(job: Job) -> bool:
    return is_internship_title(job.title) and not is_france_only(job.location)
```

- [ ] **Step 5: Write `intern_radar/ranking.py`**

```python
"""Deterministic final score computed from the LLM assessment."""

from intern_radar.config import Weights
from intern_radar.models import Assessment, Tier

TIER_POINTS = {"S": 10, "A": 8, "B": 6, "unlisted": 4}
DATES_POINTS = {"fits": 10, "unknown": 6, "too_short_extendable": 4}
LOCAL_STUDENTS_PENALTY = 2


def is_excluded(assessment: Assessment) -> bool:
    return (
        not assessment.is_internship
        or assessment.dates_fit == "incompatible"
        or assessment.eligibility == "phd_only"
        or not assessment.language_ok
    )


def final_score(tier: Tier, assessment: Assessment, weights: Weights) -> float | None:
    if is_excluded(assessment):
        return None
    score = (
        weights.tier * TIER_POINTS[tier]
        + weights.relevance * assessment.ai_relevance
        + weights.dates * DATES_POINTS[assessment.dates_fit]
    )
    if assessment.eligibility == "local_students_only":
        score -= LOCAL_STUDENTS_PENALTY
    return round(max(score, 0.0), 1)
```

- [ ] **Step 6: Run the tests to see them pass**

Run: `poetry run pytest tests/test_prefilter.py tests/test_ranking.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
poetry run ruff check . && poetry run ruff format .
git add intern_radar/prefilter.py intern_radar/ranking.py tests/test_prefilter.py tests/test_ranking.py
git commit -m "feat: add rule-based pre-filter and final score computation"
```

---

### Task 5: HTTP client, source base, Greenhouse and Lever plugins

**Files:**
- Create: `intern_radar/http.py`, `intern_radar/sources/__init__.py` (empty for now), `intern_radar/sources/base.py`, `intern_radar/sources/greenhouse.py`, `intern_radar/sources/lever.py`, `tests/test_http.py`, `tests/sources/__init__.py`, `tests/sources/test_base.py`, `tests/sources/test_greenhouse.py`, `tests/sources/test_lever.py`
- Modify: `tests/factories.py` (add `mock_client`)

**Interfaces:**
- Consumes: `models.Company`, `models.Job`, `prefilter.is_internship_title`
- Produces:
  - `http.USER_AGENT`, `http.Throttle(interval=1.0, clock=time.monotonic, sleep=time.sleep)` (callable request hook), `http.make_client(throttle: Throttle | None = None, transport: httpx.BaseTransport | None = None) -> httpx.Client`
  - `sources.base.SourceError`, `sources.base.Source` (Protocol: `fetch(company: Company, known_ids: Container[str]) -> list[Job]`)
  - `sources.base.html_to_text(markup: str) -> str`, `sources.base.iso_date(value: str | None) -> str | None`, `sources.base.require_param(company: Company, key: str) -> str`, `sources.base.get_json(client: httpx.Client, method: str, url: str, **kwargs) -> Any`
  - `sources.greenhouse.GreenhouseSource(client)` — param `board`
  - `sources.lever.LeverSource(client)` — param `site`
  - `tests.factories.mock_client(routes: dict[str, Any]) -> httpx.Client`

- [ ] **Step 1: Write `intern_radar/http.py` with its test**

`tests/test_http.py`:

```python
import httpx

from intern_radar.http import USER_AGENT, Throttle, make_client


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_throttle_spaces_requests_to_the_same_host():
    clock = FakeClock()
    throttle = Throttle(interval=1.0, clock=clock, sleep=clock.sleep)
    throttle(httpx.Request("GET", "https://a.example/1"))
    clock.now += 0.25
    throttle(httpx.Request("GET", "https://a.example/2"))
    throttle(httpx.Request("GET", "https://b.example/1"))
    assert clock.sleeps == [0.75]


def test_make_client_sets_user_agent():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["User-Agent"]
        return httpx.Response(200, json={})

    client = make_client(Throttle(interval=0), httpx.MockTransport(handler))
    client.get("https://a.example/")
    assert seen["ua"] == USER_AGENT
```

`intern_radar/http.py`:

```python
"""HTTP client shared by the source plugins."""

import time
from collections.abc import Callable

import httpx

USER_AGENT = "intern-radar/0.1 (+https://github.com/rmouahid/intern-radar)"
TIMEOUT_SECONDS = 20.0


class Throttle:
    """Request hook keeping `interval` seconds between requests to one host."""

    def __init__(
        self,
        interval: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._interval = interval
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}

    def __call__(self, request: httpx.Request) -> None:
        host = request.url.host
        last = self._last.get(host)
        if last is not None:
            wait = self._interval - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last[host] = self._clock()


def make_client(
    throttle: Throttle | None = None,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
        event_hooks={"request": [throttle or Throttle()]},
        transport=transport,
    )
```

Run: `poetry run pytest tests/test_http.py -q` → pass.

- [ ] **Step 2: Add `mock_client` to `tests/factories.py`**

Replace the import block at the top of `tests/factories.py` with:

```python
"""Builders for test objects with sensible defaults."""

from collections.abc import Callable
from datetime import date
from typing import Any

import httpx

from intern_radar.config import Profile
from intern_radar.http import Throttle, make_client
from intern_radar.models import Assessment, Job
```

and append:

```python
def mock_client(routes: dict[str, Any]) -> httpx.Client:
    """HTTP client answering from `routes`.

    Keys are "METHOD https://host/path" (query string ignored). Values are a
    JSON-serialisable body (200), an int status code, or a callable taking the
    request and returning an httpx.Response. Unknown routes answer 404.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        key = f"{request.method} {request.url.copy_with(query=None)}"
        value = routes.get(key)
        if value is None:
            return httpx.Response(404, json={"error": "not mocked", "key": key})
        if isinstance(value, int):
            return httpx.Response(value)
        if isinstance(value, Callable):
            return value(request)
        return httpx.Response(200, json=value)

    return make_client(Throttle(interval=0), httpx.MockTransport(handler))
```

- [ ] **Step 3: Write the failing tests `tests/sources/test_base.py`**

`tests/sources/__init__.py`: empty file.

```python
import pytest

from intern_radar.models import Company
from intern_radar.sources.base import (
    SourceError,
    get_json,
    html_to_text,
    iso_date,
    require_param,
)
from tests.factories import mock_client


def test_html_to_text_handles_escaped_markup():
    markup = "&lt;h2&gt;About&lt;/h2&gt;&lt;p&gt;Build &amp;amp; ship&lt;/p&gt;"
    assert html_to_text(markup) == "About\nBuild & ship"


def test_html_to_text_keeps_list_items_on_their_own_lines():
    markup = "<ul><li>Python</li><li>PyTorch</li></ul>Start:&nbsp;March<br/>2027"
    assert html_to_text(markup) == "Python\nPyTorch\nStart: March\n2027"


def test_iso_date():
    assert iso_date("2026-09-17T13:05:33-04:00") == "2026-09-17"
    assert iso_date(None) is None
    assert iso_date("") is None


def test_require_param():
    company = Company("Acme", "A", "greenhouse", {"board": "acme"})
    assert require_param(company, "board") == "acme"
    with pytest.raises(SourceError, match="Acme: missing 'site'"):
        require_param(company, "site")


def test_get_json_wraps_http_errors():
    client = mock_client({"GET https://api.example/ok": {"a": 1}})
    assert get_json(client, "GET", "https://api.example/ok") == {"a": 1}
    with pytest.raises(SourceError, match="404"):
        get_json(client, "GET", "https://api.example/missing")
```

- [ ] **Step 4: Write `intern_radar/sources/base.py`**

`intern_radar/sources/__init__.py`: empty for now (the registry is added in Task 6).

```python
"""Pieces shared by the source plugins."""

import html
import re
from collections.abc import Container
from html.parser import HTMLParser
from typing import Any, Protocol

import httpx

from intern_radar.models import Company, Job


class SourceError(Exception):
    """A source could not be fetched or parsed."""


class Source(Protocol):
    def fetch(self, company: Company, known_ids: Container[str]) -> list[Job]:
        """Return the company's internship-titled jobs not in `known_ids`."""
        ...


BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "tr", "h1", "h2", "h3", "h4"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(markup: str) -> str:
    """Plain text from HTML, including entity-escaped HTML (Greenhouse)."""
    if "&lt;" in markup:
        markup = html.unescape(markup)
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    text = re.sub(r"[ \t\xa0]+", " ", "".join(parser.parts))
    return re.sub(r"\s*\n\s*", "\n", text).strip()


def iso_date(value: str | None) -> str | None:
    return value[:10] if value else None


def require_param(company: Company, key: str) -> str:
    value = company.params.get(key)
    if not value:
        raise SourceError(f"{company.name}: missing '{key}' in companies.yaml")
    return str(value)


def get_json(client: httpx.Client, method: str, url: str, **kwargs: Any) -> Any:
    try:
        response = client.request(method, url, **kwargs)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SourceError(f"{method} {url}: {exc}") from exc
```

Run: `poetry run pytest tests/sources/test_base.py -q` → pass.

- [ ] **Step 5: Write the failing tests `tests/sources/test_greenhouse.py`**

```python
from intern_radar.models import Company, Job
from intern_radar.sources.greenhouse import GreenhouseSource
from tests.factories import mock_client

API = "https://boards-api.greenhouse.io/v1/boards/stripe/jobs"
COMPANY = Company("Stripe", "A", "greenhouse", {"board": "stripe"})

LIST = {
    "jobs": [
        {"id": 11, "title": "Machine Learning Intern", "location": {"name": "Dublin"},
         "absolute_url": "https://stripe.com/jobs/11",
         "first_published": "2026-09-10T09:00:00-04:00"},
        {"id": 12, "title": "Internal Tools Engineer", "location": {"name": "Dublin"},
         "absolute_url": "https://stripe.com/jobs/12",
         "first_published": "2026-09-11T09:00:00-04:00"},
        {"id": 13, "title": "Data Science Intern", "location": {"name": "Toronto"},
         "absolute_url": "https://stripe.com/jobs/13",
         "first_published": "2026-09-12T09:00:00-04:00"},
    ]
}
DETAIL_11 = {
    "id": 11, "title": "Machine Learning Intern", "location": {"name": "Dublin"},
    "absolute_url": "https://stripe.com/jobs/11",
    "first_published": "2026-09-10T09:00:00-04:00",
    "content": "&lt;p&gt;Train models.&lt;/p&gt;",
}


def test_fetch_returns_new_internship_jobs_with_details():
    client = mock_client({f"GET {API}": LIST, f"GET {API}/11": DETAIL_11})
    jobs = GreenhouseSource(client).fetch(COMPANY, known_ids={"greenhouse:stripe:13"})
    assert jobs == [
        Job(
            id="greenhouse:stripe:11",
            company="Stripe",
            tier="A",
            title="Machine Learning Intern",
            location="Dublin",
            url="https://stripe.com/jobs/11",
            description="Train models.",
            source="greenhouse",
            posted_at="2026-09-10",
        )
    ]
```

- [ ] **Step 6: Write `intern_radar/sources/greenhouse.py`**

```python
"""Greenhouse job boards (boards-api.greenhouse.io)."""

from collections.abc import Container

import httpx

from intern_radar.models import Company, Job
from intern_radar.prefilter import is_internship_title
from intern_radar.sources.base import get_json, html_to_text, iso_date, require_param

API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"


class GreenhouseSource:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def fetch(self, company: Company, known_ids: Container[str]) -> list[Job]:
        board = require_param(company, "board")
        url = API.format(board=board)
        listing = get_json(self._client, "GET", url)
        jobs = []
        for item in listing.get("jobs", []):
            job_id = f"greenhouse:{board}:{item['id']}"
            if job_id in known_ids or not is_internship_title(item["title"]):
                continue
            detail = get_json(self._client, "GET", f"{url}/{item['id']}")
            jobs.append(
                Job(
                    id=job_id,
                    company=company.name,
                    tier=company.tier,
                    title=item["title"].strip(),
                    location=(item.get("location") or {}).get("name", ""),
                    url=item["absolute_url"],
                    description=html_to_text(detail.get("content") or ""),
                    source="greenhouse",
                    posted_at=iso_date(
                        item.get("first_published") or item.get("updated_at")
                    ),
                )
            )
        return jobs
```

Run: `poetry run pytest tests/sources/test_greenhouse.py -q` → pass.

- [ ] **Step 7: Write the failing tests `tests/sources/test_lever.py`**

```python
from intern_radar.models import Company, Job
from intern_radar.sources.lever import LeverSource
from tests.factories import mock_client

API = "https://api.lever.co/v0/postings/palantir"
COMPANY = Company("Palantir", "A", "lever", {"site": "palantir"})

POSTINGS = [
    {
        "id": "abc", "text": "Software Engineer Intern - Singapore",
        "categories": {"location": "Singapore, Singapore",
                       "allLocations": ["Singapore, Singapore", "London, UK"]},
        "hostedUrl": "https://jobs.lever.co/palantir/abc",
        "createdAt": 1786469891368,
        "descriptionPlain": "Build software.",
        "lists": [{"text": "Requirements", "content": "<li>Python</li>"}],
        "additionalPlain": "Visa sponsorship available.",
    },
    {
        "id": "def", "text": "Administrative Partner",
        "categories": {"location": "Singapore, Singapore"},
        "hostedUrl": "https://jobs.lever.co/palantir/def",
        "createdAt": 1786469891368, "descriptionPlain": "",
    },
]


def test_fetch_maps_lever_postings():
    client = mock_client({f"GET {API}": POSTINGS})
    assert LeverSource(client).fetch(COMPANY, known_ids=set()) == [
        Job(
            id="lever:palantir:abc",
            company="Palantir",
            tier="A",
            title="Software Engineer Intern - Singapore",
            location="Singapore, Singapore; London, UK",
            url="https://jobs.lever.co/palantir/abc",
            description="Build software.\nRequirements\nPython\n"
            "Visa sponsorship available.",
            source="lever",
            posted_at="2026-08-11",
        )
    ]
```

(`1786469891368` ms = 2026-08-11 UTC.)

- [ ] **Step 8: Write `intern_radar/sources/lever.py`**

```python
"""Lever job sites (api.lever.co)."""

from collections.abc import Container
from datetime import UTC, datetime

import httpx

from intern_radar.models import Company, Job
from intern_radar.prefilter import is_internship_title
from intern_radar.sources.base import get_json, html_to_text, require_param

API = "https://api.lever.co/v0/postings/{site}"


def _description(item: dict) -> str:
    parts = [item.get("descriptionPlain") or ""]
    for block in item.get("lists") or []:
        parts.append(block.get("text", ""))
        parts.append(html_to_text(block.get("content", "")))
    parts.append(item.get("additionalPlain") or "")
    return "\n".join(part.strip() for part in parts if part.strip())


class LeverSource:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def fetch(self, company: Company, known_ids: Container[str]) -> list[Job]:
        site = require_param(company, "site")
        postings = get_json(
            self._client, "GET", API.format(site=site), params={"mode": "json"}
        )
        jobs = []
        for item in postings:
            job_id = f"lever:{site}:{item['id']}"
            if job_id in known_ids or not is_internship_title(item["text"]):
                continue
            categories = item.get("categories") or {}
            locations = categories.get("allLocations") or [
                categories.get("location", "")
            ]
            created = item.get("createdAt")
            jobs.append(
                Job(
                    id=job_id,
                    company=company.name,
                    tier=company.tier,
                    title=item["text"].strip(),
                    location="; ".join(loc for loc in locations if loc),
                    url=item["hostedUrl"],
                    description=_description(item),
                    source="lever",
                    posted_at=(
                        datetime.fromtimestamp(created / 1000, UTC).date().isoformat()
                        if created
                        else None
                    ),
                )
            )
        return jobs
```

Run: `poetry run pytest tests/sources -q` → pass.

- [ ] **Step 9: Commit**

```bash
poetry run ruff check . && poetry run ruff format .
git add intern_radar/http.py intern_radar/sources tests/test_http.py tests/sources tests/factories.py
git commit -m "feat: add throttled HTTP client and Greenhouse and Lever sources"
```

---

### Task 6: Ashby, Workable and SmartRecruiters plugins, source registry

**Files:**
- Create: `intern_radar/sources/ashby.py`, `intern_radar/sources/workable.py`, `intern_radar/sources/smartrecruiters.py`, `tests/sources/test_ashby.py`, `tests/sources/test_workable.py`, `tests/sources/test_smartrecruiters.py`, `tests/sources/test_registry.py`
- Modify: `intern_radar/sources/__init__.py`

**Interfaces:**
- Consumes: everything from Task 5
- Produces:
  - `sources.ashby.AshbySource(client)` — param `org`
  - `sources.workable.WorkableSource(client)` — param `account`
  - `sources.smartrecruiters.SmartRecruitersSource(client)` — param `company_id`
  - `sources.SOURCE_NAMES: frozenset[str]` (includes `"none"`)
  - `sources.build_sources(client: httpx.Client, companies: list[Company], profile: Profile) -> dict[str, Source]`

- [ ] **Step 1: Failing test `tests/sources/test_ashby.py`**

```python
from intern_radar.models import Company, Job
from intern_radar.sources.ashby import AshbySource
from tests.factories import mock_client

API = "https://api.ashbyhq.com/posting-api/job-board/cohere"
COMPANY = Company("Cohere", "A", "ashby", {"org": "cohere"})

BOARD = {
    "jobs": [
        {"id": "u1", "title": "Machine Learning Intern/Co-op (Winter 2027)",
         "location": "Toronto",
         "secondaryLocations": [{"location": "London"}],
         "publishedAt": "2026-09-15T18:21:37.401+00:00", "isListed": True,
         "jobUrl": "https://jobs.ashbyhq.com/cohere/u1",
         "descriptionPlain": "Work on LLMs."},
        {"id": "u2", "title": "Research Intern", "location": "Toronto",
         "secondaryLocations": [], "publishedAt": "2026-09-15T00:00:00+00:00",
         "isListed": False, "jobUrl": "https://jobs.ashbyhq.com/cohere/u2",
         "descriptionPlain": "Hidden."},
    ]
}


def test_fetch_keeps_listed_internships():
    client = mock_client({f"GET {API}": BOARD})
    assert AshbySource(client).fetch(COMPANY, known_ids=set()) == [
        Job(
            id="ashby:cohere:u1",
            company="Cohere",
            tier="A",
            title="Machine Learning Intern/Co-op (Winter 2027)",
            location="Toronto; London",
            url="https://jobs.ashbyhq.com/cohere/u1",
            description="Work on LLMs.",
            source="ashby",
            posted_at="2026-09-15",
        )
    ]
```

- [ ] **Step 2: `intern_radar/sources/ashby.py`**

```python
"""Ashby job boards (api.ashbyhq.com)."""

from collections.abc import Container

import httpx

from intern_radar.models import Company, Job
from intern_radar.prefilter import is_internship_title
from intern_radar.sources.base import get_json, iso_date, require_param

API = "https://api.ashbyhq.com/posting-api/job-board/{org}"


class AshbySource:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def fetch(self, company: Company, known_ids: Container[str]) -> list[Job]:
        org = require_param(company, "org")
        board = get_json(self._client, "GET", API.format(org=org))
        jobs = []
        for item in board.get("jobs", []):
            job_id = f"ashby:{org}:{item['id']}"
            if (
                job_id in known_ids
                or not item.get("isListed", True)
                or not is_internship_title(item["title"])
            ):
                continue
            locations = [item.get("location", "")] + [
                loc.get("location", "") for loc in item.get("secondaryLocations") or []
            ]
            jobs.append(
                Job(
                    id=job_id,
                    company=company.name,
                    tier=company.tier,
                    title=item["title"].strip(),
                    location="; ".join(loc for loc in locations if loc),
                    url=item["jobUrl"],
                    description=item.get("descriptionPlain") or "",
                    source="ashby",
                    posted_at=iso_date(item.get("publishedAt")),
                )
            )
        return jobs
```

Run: `poetry run pytest tests/sources/test_ashby.py -q` → pass.

- [ ] **Step 3: Failing test `tests/sources/test_workable.py`**

```python
from intern_radar.models import Company, Job
from intern_radar.sources.workable import WorkableSource
from tests.factories import mock_client

API = "https://apply.workable.com/api/v1/widget/accounts/huggingface"
COMPANY = Company("Hugging Face", "A", "workable", {"account": "huggingface"})

ACCOUNT = {
    "name": "Hugging Face",
    "jobs": [
        {"title": "ML Engineering Intern - EMEA Remote", "shortcode": "AB12",
         "url": "https://apply.workable.com/j/AB12", "published_on": "2026-07-30",
         "city": "", "country": "",
         "locations": [{"country": "Switzerland", "city": "Bern"},
                       {"country": "United Kingdom", "city": "London"}],
         "description": "<p>Open-source ML.</p>"},
        {"title": "Senior Engineer", "shortcode": "CD34",
         "url": "https://apply.workable.com/j/CD34", "published_on": "2026-07-30",
         "city": "Paris", "country": "France", "locations": [],
         "description": "<p>x</p>"},
    ],
}


def test_fetch_maps_workable_jobs():
    client = mock_client({f"GET {API}": ACCOUNT})
    assert WorkableSource(client).fetch(COMPANY, known_ids=set()) == [
        Job(
            id="workable:huggingface:AB12",
            company="Hugging Face",
            tier="A",
            title="ML Engineering Intern - EMEA Remote",
            location="Bern, Switzerland; London, United Kingdom",
            url="https://apply.workable.com/j/AB12",
            description="Open-source ML.",
            source="workable",
            posted_at="2026-07-30",
        )
    ]
```

- [ ] **Step 4: `intern_radar/sources/workable.py`**

```python
"""Workable accounts (apply.workable.com widget API)."""

from collections.abc import Container

import httpx

from intern_radar.models import Company, Job
from intern_radar.prefilter import is_internship_title
from intern_radar.sources.base import get_json, html_to_text, require_param

API = "https://apply.workable.com/api/v1/widget/accounts/{account}"


def _place(city: str, country: str) -> str:
    return ", ".join(part for part in (city, country) if part)


class WorkableSource:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def fetch(self, company: Company, known_ids: Container[str]) -> list[Job]:
        account = require_param(company, "account")
        data = get_json(
            self._client,
            "GET",
            API.format(account=account),
            params={"details": "true"},
        )
        jobs = []
        for item in data.get("jobs", []):
            job_id = f"workable:{account}:{item['shortcode']}"
            if job_id in known_ids or not is_internship_title(item["title"]):
                continue
            places = [
                _place(loc.get("city", ""), loc.get("country", ""))
                for loc in item.get("locations") or []
            ] or [_place(item.get("city", ""), item.get("country", ""))]
            jobs.append(
                Job(
                    id=job_id,
                    company=company.name,
                    tier=company.tier,
                    title=item["title"].strip(),
                    location="; ".join(place for place in places if place),
                    url=item["url"],
                    description=html_to_text(item.get("description") or ""),
                    source="workable",
                    posted_at=item.get("published_on"),
                )
            )
        return jobs
```

Run: `poetry run pytest tests/sources/test_workable.py -q` → pass.

- [ ] **Step 5: Failing test `tests/sources/test_smartrecruiters.py`**

```python
import httpx

from intern_radar.models import Company, Job
from intern_radar.sources.smartrecruiters import SmartRecruitersSource
from tests.factories import mock_client

API = "https://api.smartrecruiters.com/v1/companies/BoschGroup/postings"
COMPANY = Company("Bosch", "B", "smartrecruiters", {"company_id": "BoschGroup"})


def listing(request: httpx.Request) -> httpx.Response:
    offset = int(request.url.params["offset"])
    assert request.url.params["q"] == "intern"
    pages = {
        0: [{"id": "1", "name": "AI Research Intern",
             "location": {"fullLocation": "Renningen, BW, Germany"},
             "releasedDate": "2026-09-24T14:50:48.550Z"},
            {"id": "2", "name": "System Architect",
             "location": {"fullLocation": "Stuttgart, Germany"},
             "releasedDate": "2026-09-24T14:50:48.550Z"}],
    }
    content = pages.get(offset, [])
    return httpx.Response(200, json={"offset": offset, "limit": 100,
                                     "totalFound": 2, "content": content})


DETAIL = {
    "id": "1",
    "postingUrl": "https://jobs.smartrecruiters.com/BoschGroup/1-ai-research-intern",
    "jobAd": {"sections": {
        "jobDescription": {"title": "Job Description", "text": "<p>LLM research.</p>"},
        "qualifications": {"title": "Qualifications", "text": "<ul><li>Python</li></ul>"},
    }},
}


def test_fetch_lists_then_reads_internship_details():
    client = mock_client({f"GET {API}": listing, f"GET {API}/1": DETAIL})
    assert SmartRecruitersSource(client).fetch(COMPANY, known_ids=set()) == [
        Job(
            id="smartrecruiters:BoschGroup:1",
            company="Bosch",
            tier="B",
            title="AI Research Intern",
            location="Renningen, BW, Germany",
            url="https://jobs.smartrecruiters.com/BoschGroup/1-ai-research-intern",
            description="LLM research.\nPython",
            source="smartrecruiters",
            posted_at="2026-09-24",
        )
    ]
```

- [ ] **Step 6: `intern_radar/sources/smartrecruiters.py`**

```python
"""SmartRecruiters public postings API."""

from collections.abc import Container

import httpx

from intern_radar.models import Company, Job
from intern_radar.prefilter import is_internship_title
from intern_radar.sources.base import get_json, html_to_text, iso_date, require_param

API = "https://api.smartrecruiters.com/v1/companies/{company_id}/postings"
PAGE_SIZE = 100
MAX_PAGES = 3


class SmartRecruitersSource:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def fetch(self, company: Company, known_ids: Container[str]) -> list[Job]:
        company_id = require_param(company, "company_id")
        url = API.format(company_id=company_id)
        jobs = []
        for page in range(MAX_PAGES):
            data = get_json(
                self._client,
                "GET",
                url,
                params={"q": "intern", "limit": PAGE_SIZE, "offset": page * PAGE_SIZE},
            )
            items = data.get("content", [])
            for item in items:
                job_id = f"smartrecruiters:{company_id}:{item['id']}"
                if job_id in known_ids or not is_internship_title(item["name"]):
                    continue
                detail = get_json(self._client, "GET", f"{url}/{item['id']}")
                sections = (detail.get("jobAd") or {}).get("sections") or {}
                description = "\n".join(
                    html_to_text(section.get("text", ""))
                    for key, section in sections.items()
                    if key != "companyDescription"
                )
                jobs.append(
                    Job(
                        id=job_id,
                        company=company.name,
                        tier=company.tier,
                        title=item["name"].strip(),
                        location=(item.get("location") or {}).get("fullLocation", ""),
                        url=detail.get("postingUrl")
                        or f"https://jobs.smartrecruiters.com/{company_id}/{item['id']}",
                        description=description,
                        source="smartrecruiters",
                        posted_at=iso_date(item.get("releasedDate")),
                    )
                )
            if len(items) < PAGE_SIZE:
                break
        return jobs
```

Run: `poetry run pytest tests/sources/test_smartrecruiters.py -q` → pass.

- [ ] **Step 7: Registry — failing test `tests/sources/test_registry.py`**

```python
from intern_radar.sources import SOURCE_NAMES, build_sources
from tests.factories import make_profile, mock_client


def test_registry_builds_every_named_source():
    sources = build_sources(mock_client({}), companies=[], profile=make_profile())
    assert set(sources) | {"none"} == SOURCE_NAMES
    assert all(hasattr(source, "fetch") for source in sources.values())
```

- [ ] **Step 8: Write `intern_radar/sources/__init__.py`**

```python
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
```

(`companies` and `profile` are used by the Adzuna source added in Task 12.)

Run: `poetry run pytest -q` → all pass.

- [ ] **Step 9: Commit and open the milestone 2 PR**

```bash
poetry run ruff check . && poetry run ruff format .
git add intern_radar/sources tests/sources
git commit -m "feat: add Ashby, Workable and SmartRecruiters sources and registry"
git fetch origin && git rebase origin/develop && poetry run pytest -q
git push -u origin feature/2-ats-sources
gh pr create --base develop --title "feat: ATS source plugins and pre-filter" --body "Milestone 2: throttled HTTP client, Greenhouse, Lever, Ashby, Workable and SmartRecruiters plugins, source registry, rule-based pre-filter and final score.

Tests: \`poetry run pytest -q\` passes locally.

Closes #2"
```

After the user merges: `git switch develop && git pull --ff-only && git switch -c feature/3-scoring`.

---

### Task 7: LLM scorer

**Files:**
- Create: `intern_radar/scorer.py`, `tests/test_scorer.py`

**Interfaces:**
- Consumes: `models.Job`, `models.Assessment`, `models.DATES_FIT_VALUES`, `models.ELIGIBILITY_VALUES`
- Produces:
  - `scorer.LLMError`, `scorer.LLMBackend` (Protocol: `complete(prompt: str, schema: dict[str, Any]) -> dict[str, Any]`)
  - `scorer.ASSESSMENT_SCHEMA: dict`, `scorer.DESCRIPTION_LIMIT = 3000`
  - `scorer.ClaudeCliBackend(model: str = "haiku", timeout: int = 600, runner=subprocess.run)`
  - `scorer.Scorer(backend: LLMBackend, candidate_summary: str, window_start: date, window_end: date, min_months: int)` with `build_prompt(jobs: list[Job]) -> str` and `assess(jobs: list[Job]) -> dict[str, Assessment]` (raises `LLMError`)

- [ ] **Step 1: Failing tests `tests/test_scorer.py`**

```python
import json
import subprocess
from datetime import date

import pytest

from intern_radar.scorer import (
    ASSESSMENT_SCHEMA,
    ClaudeCliBackend,
    LLMError,
    Scorer,
)
from tests.factories import make_assessment, make_job


class FakeBackend:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.prompts: list[str] = []

    def complete(self, prompt, schema):
        assert schema is ASSESSMENT_SCHEMA
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.result


def item(job_id, **overrides):
    values = {"job_id": job_id, "is_internship": True, "ai_relevance": 8,
              "dates_fit": "fits", "eligibility": "ok",
              "visa_note": "UK: GAE scheme via a sponsor", "language_ok": True,
              "summary": "Applied ML on LLM agents."}
    values.update(overrides)
    return values


def make_scorer(backend):
    return Scorer(backend, "RAG and LLM student.", date(2027, 3, 8),
                  date(2027, 8, 31), 4)


def test_prompt_contains_profile_window_and_truncated_jobs():
    backend = FakeBackend({"assessments": []})
    long_job = make_job(id="j1", description="x" * 5000)
    make_scorer(backend).assess([long_job])
    prompt = backend.prompts[0]
    assert "RAG and LLM student." in prompt
    assert "2027-03-08 to 2027-08-31" in prompt
    assert "at least 4 months" in prompt
    assert "job_id: j1" in prompt
    assert "x" * 3000 in prompt and "x" * 3001 not in prompt


def test_assess_maps_answers_by_job_id():
    backend = FakeBackend({"assessments": [item("j2", ai_relevance=3), item("j1")]})
    result = make_scorer(backend).assess([make_job(id="j1"), make_job(id="j2")])
    assert result == {
        "j1": make_assessment(),
        "j2": make_assessment(ai_relevance=3),
    }


def test_invalid_items_are_skipped():
    backend = FakeBackend({"assessments": [
        item("j1", dates_fit="maybe"),
        item("j2", is_internship="yes"),
        item("j3", ai_relevance=14),
        item("unknown-job"),
        {"job_id": "j4"},
    ]})
    jobs = [make_job(id=f"j{i}") for i in range(1, 6)]
    result = make_scorer(backend).assess(jobs)
    assert result == {"j3": make_assessment(ai_relevance=10)}


def test_assess_empty_list_does_not_call_backend():
    backend = FakeBackend(error=AssertionError("should not be called"))
    assert make_scorer(backend).assess([]) == {}


def test_backend_errors_propagate():
    backend = FakeBackend(error=LLMError("quota"))
    with pytest.raises(LLMError, match="quota"):
        make_scorer(backend).assess([make_job()])


class FakeRunner:
    def __init__(self, returncode=0, stdout="", stderr="", exc=None):
        self.returncode, self.stdout, self.stderr, self.exc = (
            returncode, stdout, stderr, exc)
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(
            command, self.returncode, self.stdout, self.stderr)


def test_claude_backend_builds_the_command_and_reads_structured_output():
    envelope = {"type": "result", "is_error": False,
                "structured_output": {"assessments": []}}
    runner = FakeRunner(stdout=json.dumps(envelope))
    backend = ClaudeCliBackend(model="haiku", runner=runner)
    assert backend.complete("PROMPT", {"type": "object"}) == {"assessments": []}
    command, kwargs = runner.calls[0]
    assert command[:4] == ["claude", "-p", "--model", "haiku"]
    assert "--json-schema" in command
    assert command[command.index("--json-schema") + 1] == '{"type": "object"}'
    assert command[command.index("--tools") + 1] == ""
    assert kwargs["input"] == "PROMPT"


@pytest.mark.parametrize(
    "runner, message",
    [
        (FakeRunner(returncode=1, stderr="usage limit reached"), "usage limit"),
        (FakeRunner(stdout="not json"), "invalid JSON"),
        (FakeRunner(stdout=json.dumps({"is_error": True, "result": "overloaded"})),
         "overloaded"),
        (FakeRunner(exc=FileNotFoundError("claude")), "failed to run"),
        (FakeRunner(exc=subprocess.TimeoutExpired("claude", 600)), "failed to run"),
    ],
)
def test_claude_backend_failures_raise_llm_error(runner, message):
    with pytest.raises(LLMError, match=message):
        ClaudeCliBackend(runner=runner).complete("P", {})
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `poetry run pytest tests/test_scorer.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'intern_radar.scorer'`.

- [ ] **Step 3: Write `intern_radar/scorer.py`**

```python
"""LLM assessment of candidate internships through the claude CLI."""

import json
import subprocess
from collections.abc import Callable
from datetime import date
from typing import Any, Protocol

from intern_radar.models import (
    DATES_FIT_VALUES,
    ELIGIBILITY_VALUES,
    Assessment,
    Job,
)

DESCRIPTION_LIMIT = 3000

ASSESSMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                    "is_internship": {"type": "boolean"},
                    "ai_relevance": {"type": "integer", "minimum": 0, "maximum": 10},
                    "dates_fit": {"type": "string", "enum": list(DATES_FIT_VALUES)},
                    "eligibility": {
                        "type": "string",
                        "enum": list(ELIGIBILITY_VALUES),
                    },
                    "visa_note": {"type": "string"},
                    "language_ok": {"type": "boolean"},
                    "summary": {"type": "string"},
                },
                "required": [
                    "job_id",
                    "is_internship",
                    "ai_relevance",
                    "dates_fit",
                    "eligibility",
                    "visa_note",
                    "language_ok",
                    "summary",
                ],
            },
        }
    },
    "required": ["assessments"],
}

INSTRUCTIONS = """You assess internship offers for one candidate.

Candidate:
{summary}

Internship window: {start} to {end}. Minimum duration: {months} months.

Return one assessment per job below, with the same job_id:
- is_internship: true only for an internship, co-op or placement for students.
- ai_relevance: 0-10, how close the role is to AI/ML engineering (LLMs, RAG,
  agents, ML infrastructure, data) and to the candidate's skills.
- dates_fit: "fits" if it can start inside the window and last at least
  {months} months within it; "too_short_extendable" if it starts inside the
  window but lasts less than {months} months (e.g. a 12-week summer
  internship); "incompatible" if it cannot start inside the window (e.g. a
  January-April co-op, a fall internship); "unknown" if the posting does not
  say.
- eligibility: "phd_only" if a PhD enrolment is required;
  "local_students_only" if applicants must be enrolled at a university in the
  job's country; "ok" if a student from a French engineering school can
  apply; "unknown" otherwise.
- visa_note: one short sentence on the work authorisation a French citizen
  needs for this location, or what the posting says about sponsorship.
- language_ok: false if the role requires a language other than English,
  Spanish or French.
- summary: one sentence describing the role.

Jobs:
"""


class LLMError(Exception):
    """The LLM backend could not produce an answer."""


class LLMBackend(Protocol):
    def complete(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]: ...


class ClaudeCliBackend:
    """Runs `claude -p` with structured output, using the logged-in session."""

    def __init__(
        self,
        model: str = "haiku",
        timeout: int = 600,
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        self._model = model
        self._timeout = timeout
        self._runner = runner

    def complete(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        command = [
            "claude",
            "-p",
            "--model",
            self._model,
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(schema),
            "--tools",
            "",
            "--no-session-persistence",
            "--strict-mcp-config",
        ]
        try:
            proc = self._runner(
                command,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LLMError(f"claude CLI failed to run: {exc}") from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:300]
            raise LLMError(f"claude CLI exited with {proc.returncode}: {detail}")
        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise LLMError("claude CLI returned invalid JSON") from exc
        output = envelope.get("structured_output")
        if envelope.get("is_error") or not isinstance(output, dict):
            detail = str(envelope.get("result", ""))[:300]
            raise LLMError(f"claude CLI returned no structured output: {detail}")
        return output


def _parse(item: Any) -> Assessment | None:
    if not isinstance(item, dict):
        return None
    try:
        booleans = (item["is_internship"], item["language_ok"])
        relevance = item["ai_relevance"]
        dates_fit, eligibility = item["dates_fit"], item["eligibility"]
        visa_note, summary = item["visa_note"], item["summary"]
    except KeyError:
        return None
    if not all(isinstance(value, bool) for value in booleans):
        return None
    if not isinstance(relevance, int) or isinstance(relevance, bool):
        return None
    if dates_fit not in DATES_FIT_VALUES or eligibility not in ELIGIBILITY_VALUES:
        return None
    return Assessment(
        is_internship=item["is_internship"],
        ai_relevance=min(max(relevance, 0), 10),
        dates_fit=dates_fit,
        eligibility=eligibility,
        visa_note=str(visa_note),
        language_ok=item["language_ok"],
        summary=str(summary),
    )


class Scorer:
    def __init__(
        self,
        backend: LLMBackend,
        candidate_summary: str,
        window_start: date,
        window_end: date,
        min_months: int,
    ) -> None:
        self._backend = backend
        self._header = INSTRUCTIONS.format(
            summary=candidate_summary.strip(),
            start=window_start.isoformat(),
            end=window_end.isoformat(),
            months=min_months,
        )

    def build_prompt(self, jobs: list[Job]) -> str:
        blocks = [
            f"--- job_id: {job.id}\n"
            f"Company: {job.company}\n"
            f"Title: {job.title}\n"
            f"Location: {job.location or 'not stated'}\n"
            f"Description:\n{job.description[:DESCRIPTION_LIMIT]}\n"
            for job in jobs
        ]
        return self._header + "\n".join(blocks)

    def assess(self, jobs: list[Job]) -> dict[str, Assessment]:
        if not jobs:
            return {}
        result = self._backend.complete(self.build_prompt(jobs), ASSESSMENT_SCHEMA)
        wanted = {job.id for job in jobs}
        assessments: dict[str, Assessment] = {}
        for item in result.get("assessments", []):
            parsed = _parse(item)
            job_id = item.get("job_id") if isinstance(item, dict) else None
            if parsed is not None and job_id in wanted:
                assessments[job_id] = parsed
        return assessments
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `poetry run pytest tests/test_scorer.py -q`
Expected: all pass.

- [ ] **Step 5: Manual check against the real CLI (not in CI)**

```bash
poetry run python -c "
from datetime import date
from intern_radar.scorer import ClaudeCliBackend, Scorer
from tests.factories import make_job
s = Scorer(ClaudeCliBackend(), 'RAG/LLM engineering student.', date(2027,3,8), date(2027,8,31), 4)
print(s.assess([make_job(id='t1', title='Machine Learning Intern (6 months, from March 2027)', location='London, UK', description='Work on LLM agents for 6 months starting March 2027. Open to EU students.')]))
"
```

Expected: `{'t1': Assessment(is_internship=True, ai_relevance=…, dates_fit='fits', …)}`.

- [ ] **Step 6: Commit and open the milestone 3 PR**

```bash
poetry run ruff check . && poetry run ruff format .
git add intern_radar/scorer.py tests/test_scorer.py
git commit -m "feat: score candidate internships through the claude CLI"
git fetch origin && git rebase origin/develop && poetry run pytest -q
git push -u origin feature/3-scoring
gh pr create --base develop --title "feat: LLM scoring through the claude CLI" --body "Milestone 3: batched structured-output assessment of candidate internships with \`claude -p --json-schema\`, strict validation of every returned item.

Tests: \`poetry run pytest -q\` passes; manual run against the real CLI returned a valid assessment.

Closes #3"
```

After the merge: `git switch develop && git pull --ff-only && git switch -c feature/4-notifications-cli`.

---

### Task 8: ntfy notifier and message formatting

**Files:**
- Create: `intern_radar/notifier.py`, `tests/test_notifier.py`

**Interfaces:**
- Consumes: `models.ScoredJob`
- Produces:
  - `notifier.NotifyError`, `notifier.Message(title: str, body: str, priority: int = 3, tags: tuple[str, ...] = (), click: str | None = None, actions: tuple[tuple[str, str], ...] = ())`
  - `notifier.Notifier` (Protocol: `send(message: Message) -> None`)
  - `notifier.NtfyNotifier(server: str, topic: str, client: httpx.Client)`, `notifier.ConsoleNotifier(write=print)`
  - `notifier.format_immediate(scored: ScoredJob) -> Message`, `notifier.format_digest(jobs: list[ScoredJob]) -> Message`, `notifier.format_source_alert(company: str, error: str) -> Message`, `notifier.format_llm_alert() -> Message`, `notifier.MAX_DIGEST_LINES = 20`

- [ ] **Step 1: Failing tests `tests/test_notifier.py`**

```python
import json

import httpx
import pytest

from intern_radar.models import ScoredJob
from intern_radar.notifier import (
    ConsoleNotifier,
    Message,
    NotifyError,
    NtfyNotifier,
    format_digest,
    format_immediate,
    format_llm_alert,
    format_source_alert,
)
from tests.factories import make_assessment, make_job, mock_client


def scored(job_id="j1", score=9.7, **job_overrides):
    return ScoredJob(make_job(id=job_id, **job_overrides), make_assessment(), score)


def test_format_immediate():
    message = format_immediate(scored(company="Google DeepMind", tier="S",
                                      title="Research Engineer Intern"))
    assert message.title == "[S] Google DeepMind — Research Engineer Intern"
    assert message.body == (
        "📍 London, UK · score 9.7\n"
        "📅 dates OK · 🛂 UK: GAE scheme via a sponsor\n"
        "Applied ML on LLM agents."
    )
    assert message.priority == 4
    assert message.tags == ("fire",)
    assert message.click == "https://example.com/jobs/1"
    assert message.actions == (("View offer", "https://example.com/jobs/1"),)


def test_format_digest_lists_offers():
    message = format_digest([scored("a", 7.1, company="Databricks",
                                    title="ML Intern", location="Amsterdam")])
    assert message.title == "Digest — 1 offer"
    assert message.body == "• [A] Databricks — ML Intern · Amsterdam · 7.1"
    assert message.priority == 3


def test_digest_is_truncated_after_20_lines():
    jobs = [scored(f"j{i}", 6.0, title="Machine Learning Intern " * 3)
            for i in range(45)]
    message = format_digest(jobs)
    lines = message.body.split("\n")
    assert message.title == "Digest — 45 offers"
    assert len(lines) == 21
    assert lines[-1] == "… and 25 more (intern-radar list)"
    assert len(message.body.encode()) < 4096


def test_alert_messages():
    assert format_source_alert("Acme", "HTTP 500").title == "Source broken: Acme"
    assert "HTTP 500" in format_source_alert("Acme", "HTTP 500").body
    assert format_llm_alert().priority == 2


def test_ntfy_notifier_posts_json_to_the_server_root():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "x"})

    client = mock_client({"POST https://ntfy.sh/": handler})
    message = Message("T", "B", 4, ("fire",), "https://u", (("View offer", "https://u"),))
    NtfyNotifier("https://ntfy.sh/", "topic-1", client).send(message)
    assert seen["body"] == {
        "topic": "topic-1", "title": "T", "message": "B", "priority": 4,
        "tags": ["fire"], "click": "https://u",
        "actions": [{"action": "view", "label": "View offer", "url": "https://u"}],
    }


def test_ntfy_notifier_raises_on_http_error():
    client = mock_client({"POST https://ntfy.sh/": 429})
    with pytest.raises(NotifyError):
        NtfyNotifier("https://ntfy.sh", "t", client).send(Message("T", "B"))


def test_console_notifier_writes_the_message():
    lines = []
    ConsoleNotifier(write=lines.append).send(Message("T", "B", 4))
    assert lines == ["[priority 4] T\nB\n"]
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `poetry run pytest tests/test_notifier.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `intern_radar/notifier.py`**

```python
"""ntfy notifications and their formatting."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from intern_radar.models import ScoredJob

MAX_DIGEST_LINES = 20
DATES_LABELS = {
    "fits": "dates OK",
    "too_short_extendable": "too short, ask to extend",
    "unknown": "dates not stated",
    "incompatible": "dates incompatible",
}


class NotifyError(Exception):
    """A notification could not be delivered."""


@dataclass(frozen=True)
class Message:
    title: str
    body: str
    priority: int = 3
    tags: tuple[str, ...] = ()
    click: str | None = None
    actions: tuple[tuple[str, str], ...] = ()


class Notifier(Protocol):
    def send(self, message: Message) -> None: ...


class NtfyNotifier:
    def __init__(self, server: str, topic: str, client: httpx.Client) -> None:
        self._server = server.rstrip("/") + "/"
        self._topic = topic
        self._client = client

    def send(self, message: Message) -> None:
        payload: dict[str, Any] = {
            "topic": self._topic,
            "title": message.title,
            "message": message.body,
            "priority": message.priority,
            "tags": list(message.tags),
        }
        if message.click:
            payload["click"] = message.click
        if message.actions:
            payload["actions"] = [
                {"action": "view", "label": label, "url": url}
                for label, url in message.actions
            ]
        try:
            response = self._client.post(self._server, json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise NotifyError(f"ntfy: {exc}") from exc


class ConsoleNotifier:
    """Prints messages instead of sending them (dry runs)."""

    def __init__(self, write: Callable[[str], Any] = print) -> None:
        self._write = write

    def send(self, message: Message) -> None:
        self._write(f"[priority {message.priority}] {message.title}\n{message.body}\n")


def format_immediate(scored: ScoredJob) -> Message:
    job, assessment = scored.job, scored.assessment
    body = "\n".join(
        [
            f"📍 {job.location or 'location not stated'} · score {scored.score:.1f}",
            f"📅 {DATES_LABELS[assessment.dates_fit]} · 🛂 {assessment.visa_note}",
            assessment.summary,
        ]
    )
    return Message(
        title=f"[{job.tier}] {job.company} — {job.title}",
        body=body,
        priority=4,
        tags=("fire",),
        click=job.url,
        actions=(("View offer", job.url),),
    )


def format_digest(jobs: list[ScoredJob]) -> Message:
    lines = [
        f"• [{s.job.tier}] {s.job.company} — {s.job.title[:80]}"
        f" · {s.job.location[:40]} · {s.score:.1f}"
        for s in jobs[:MAX_DIGEST_LINES]
    ]
    if len(jobs) > MAX_DIGEST_LINES:
        lines.append(f"… and {len(jobs) - MAX_DIGEST_LINES} more (intern-radar list)")
    noun = "offer" if len(jobs) == 1 else "offers"
    return Message(
        title=f"Digest — {len(jobs)} {noun}",
        body="\n".join(lines),
        priority=3,
        tags=("clipboard",),
    )


def format_source_alert(company: str, error: str) -> Message:
    return Message(
        title=f"Source broken: {company}",
        body=f"Failing for 3 days. Last error: {error[:300]}",
        priority=2,
        tags=("warning",),
    )


def format_llm_alert() -> Message:
    return Message(
        title="LLM scoring unavailable",
        body="claude -p has been failing for a day; offers are waiting to be scored.",
        priority=2,
        tags=("warning",),
    )
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `poetry run pytest tests/test_notifier.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
poetry run ruff check . && poetry run ruff format .
git add intern_radar/notifier.py tests/test_notifier.py
git commit -m "feat: add ntfy notifier and message formatting"
```

---

### Task 9: Pipeline

**Files:**
- Create: `intern_radar/pipeline.py`, `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `Store` (Task 3), `prefilter.passes`, `ranking.final_score` (Task 4), `Source` (Task 5), `Scorer`, `LLMError` (Task 7), `Notifier`, `NotifyError`, `format_*` (Task 8), `Profile` (Task 2)
- Produces:
  - `pipeline.RunReport(fetched=0, new=0, candidates=0, scored=0, notified=0, errors=[])`
  - `pipeline.Pipeline(companies, sources, store, scorer, notifier, profile, clock=utcnow)` with `run() -> RunReport` and `digest() -> int` (raises `NotifyError`)
  - `pipeline.BATCH_SIZE = 10`, `pipeline.SOURCE_ALERT_AFTER = timedelta(days=3)`, `pipeline.LLM_ALERT_AFTER = timedelta(days=1)`

- [ ] **Step 1: Failing tests `tests/test_pipeline.py`**

```python
from datetime import UTC, datetime, timedelta

import pytest

from intern_radar.models import Company
from intern_radar.notifier import NotifyError
from intern_radar.pipeline import Pipeline
from intern_radar.scorer import LLMError
from intern_radar.sources.base import SourceError
from intern_radar.store import Store
from tests.factories import make_assessment, make_job, make_profile

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


class FakeSource:
    def __init__(self, jobs=None, error=None):
        self.jobs = jobs or []
        self.error = error
        self.calls = []

    def fetch(self, company, known_ids):
        self.calls.append((company.name, set(known_ids)))
        if self.error:
            raise self.error
        return [job for job in self.jobs if job.id not in known_ids]


class FakeScorer:
    """Returns the assessment registered per job id; missing ids are skipped."""

    def __init__(self, answers=None, error=None):
        self.answers = answers or {}
        self.error = error
        self.batches = []

    def assess(self, jobs):
        self.batches.append([job.id for job in jobs])
        if self.error:
            raise self.error
        return {job.id: self.answers[job.id] for job in jobs if job.id in self.answers}


class FakeNotifier:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send(self, message):
        if self.fail:
            raise NotifyError("ntfy down")
        self.sent.append(message)


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


ACME = Company("Acme", "S", "fake", {})


def build(sources, scorer, notifier=None, companies=(ACME,), **profile):
    store = Store(":memory:")
    clock = Clock()
    pipeline = Pipeline(list(companies), sources, store, scorer,
                        notifier or FakeNotifier(), make_profile(**profile), clock)
    return pipeline, store, clock


def test_run_collects_filters_scores_and_notifies():
    jobs = [
        make_job(id="good", tier="S", title="ML Intern", location="London"),
        make_job(id="paris", tier="S", title="ML Intern", location="Paris, France"),
        make_job(id="eng", tier="S", title="ML Engineer", location="London"),
    ]
    scorer = FakeScorer({"good": make_assessment(ai_relevance=9)})
    notifier = FakeNotifier()
    pipeline, store, _ = build({"fake": FakeSource(jobs)}, scorer, notifier)

    report = pipeline.run()

    assert (report.fetched, report.new, report.candidates) == (3, 3, 1)
    assert (report.scored, report.notified, report.errors) == (1, 1, [])
    assert scorer.batches == [["good"]]
    assert [m.title for m in notifier.sent] == ["[S] Acme — ML Intern"]
    assert store.known_ids() == {"good", "paris", "eng"}


def test_second_run_skips_known_jobs_and_does_not_renotify():
    source = FakeSource([make_job(id="good", tier="S")])
    scorer = FakeScorer({"good": make_assessment(ai_relevance=9)})
    notifier = FakeNotifier()
    pipeline, _, _ = build({"fake": source}, scorer, notifier)
    pipeline.run()
    report = pipeline.run()
    assert report.new == 0
    assert source.calls[1][1] == {"good"}
    assert len(notifier.sent) == 1


def test_companies_without_feed_are_skipped_and_unknown_sources_are_errors():
    companies = [Company("Meta", "S", "none", {}), Company("X", "A", "gone", {})]
    pipeline, _, _ = build({}, FakeScorer(), companies=companies)
    report = pipeline.run()
    assert report.errors == ["X: unknown source 'gone'"]


def test_a_failing_source_does_not_stop_the_run():
    companies = [Company("Broken", "A", "broken", {}), ACME]
    sources = {"broken": FakeSource(error=SourceError("HTTP 500")),
               "fake": FakeSource([make_job(id="good", tier="S")])}
    scorer = FakeScorer({"good": make_assessment()})
    pipeline, _, _ = build(sources, scorer, companies=companies)
    report = pipeline.run()
    assert report.errors == ["Broken: HTTP 500"]
    assert report.scored == 1


def test_llm_failure_keeps_jobs_pending_without_attempt():
    pipeline, store, _ = build({"fake": FakeSource([make_job(id="good")])},
                               FakeScorer(error=LLMError("quota")))
    for _ in range(4):
        report = pipeline.run()
    assert report.errors == ["LLM: quota"]
    assert [job.id for job in store.pending()] == ["good"]


def test_jobs_missing_from_the_answer_are_retried_three_times():
    scorer = FakeScorer({})
    pipeline, store, _ = build({"fake": FakeSource([make_job(id="odd")])}, scorer)
    for _ in range(4):
        pipeline.run()
    assert scorer.batches == [["odd"], ["odd"], ["odd"]]
    assert store.pending() == []


def test_caps_llm_batches_and_immediate_notifications():
    jobs = [make_job(id=f"j{i:02d}", tier="S") for i in range(25)]
    answers = {job.id: make_assessment(ai_relevance=9) for job in jobs}
    scorer = FakeScorer(answers)
    notifier = FakeNotifier()
    pipeline, _, _ = build({"fake": FakeSource(jobs)}, scorer, notifier,
                           max_llm_batches_per_run=2, max_immediate_per_run=5)
    report = pipeline.run()
    assert [len(batch) for batch in scorer.batches] == [10, 10]
    assert (report.scored, report.notified) == (20, 5)
    pipeline.run()
    assert [len(batch) for batch in scorer.batches] == [10, 10, 5]
    assert len(notifier.sent) == 10


def test_notification_failure_leaves_offers_for_the_next_run():
    scorer = FakeScorer({"good": make_assessment(ai_relevance=9)})
    failing = FakeNotifier(fail=True)
    pipeline, store, _ = build({"fake": FakeSource([make_job(id="good", tier="S")])},
                               scorer, failing)
    report = pipeline.run()
    assert report.notified == 0
    assert report.errors == ["ntfy down"]
    assert [s.job.id for s in store.due_immediate(7.5, limit=10)] == ["good"]


def test_adzuna_duplicates_of_ats_jobs_are_not_scored():
    companies = [ACME, Company("Adzuna", "unlisted", "adzuna", {})]
    sources = {
        "fake": FakeSource([make_job(id="gh:1", company="Acme", title="ML Intern")]),
        "adzuna": FakeSource([make_job(id="adzuna:1", company="Acme",
                                       title="ML intern", source="adzuna")]),
    }
    scorer = FakeScorer({"gh:1": make_assessment()})
    pipeline, _, _ = build(sources, scorer, companies=companies)
    report = pipeline.run()
    assert report.candidates == 1
    assert scorer.batches == [["gh:1"]]


def test_source_alert_after_three_days():
    source = FakeSource(error=SourceError("HTTP 500"))
    notifier = FakeNotifier()
    pipeline, _, clock = build({"fake": source}, FakeScorer(), notifier)
    pipeline.run()
    clock.now = NOW + timedelta(days=3)
    pipeline.run()
    pipeline.run()
    assert [m.title for m in notifier.sent] == ["Source broken: Acme"]


def test_llm_alert_after_a_day():
    notifier = FakeNotifier()
    pipeline, _, clock = build({"fake": FakeSource([make_job(id="good")])},
                               FakeScorer(error=LLMError("quota")), notifier)
    pipeline.run()
    clock.now = NOW + timedelta(days=1)
    pipeline.run()
    assert [m.title for m in notifier.sent] == ["LLM scoring unavailable"]


def test_digest_sends_middle_band_once():
    answers = {"mid": make_assessment(ai_relevance=5, dates_fit="unknown"),
               "top": make_assessment(ai_relevance=10)}
    jobs = [make_job(id="mid", tier="B"), make_job(id="top", tier="S")]
    notifier = FakeNotifier()
    pipeline, _, _ = build({"fake": FakeSource(jobs)}, FakeScorer(answers), notifier)
    pipeline.run()
    notifier.sent.clear()
    assert pipeline.digest() == 1
    assert notifier.sent[0].title == "Digest — 1 offer"
    assert pipeline.digest() == 0
    assert len(notifier.sent) == 1


def test_digest_failure_raises_and_keeps_offers():
    answers = {"mid": make_assessment(ai_relevance=5, dates_fit="unknown")}
    pipeline, store, _ = build({"fake": FakeSource([make_job(id="mid", tier="B")])},
                               FakeScorer(answers), FakeNotifier(fail=True))
    pipeline.run()
    with pytest.raises(NotifyError):
        pipeline.digest()
    assert len(store.due_digest(5.5, 7.5)) == 1
```

(Scores used above: `mid` = 0.5·6 + 0.3·5 + 0.2·6 = 5.7 → digest; `top` = 10 → immediate; default factory job tier "A" with relevance 8, dates fits = 8.4 → immediate.)

- [ ] **Step 2: Run the tests to see them fail**

Run: `poetry run pytest tests/test_pipeline.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'intern_radar.pipeline'`.

- [ ] **Step 3: Write `intern_radar/pipeline.py`**

```python
"""Orchestrates one watch run and the evening digest."""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from intern_radar import prefilter, ranking
from intern_radar.config import Profile
from intern_radar.models import Company
from intern_radar.notifier import (
    Notifier,
    NotifyError,
    format_digest,
    format_immediate,
    format_llm_alert,
    format_source_alert,
)
from intern_radar.scorer import LLMError, Scorer
from intern_radar.sources.base import Source
from intern_radar.store import Store

log = logging.getLogger(__name__)

BATCH_SIZE = 10
SOURCE_ALERT_AFTER = timedelta(days=3)
LLM_ALERT_AFTER = timedelta(days=1)


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class RunReport:
    fetched: int = 0
    new: int = 0
    candidates: int = 0
    scored: int = 0
    notified: int = 0
    errors: list[str] = field(default_factory=list)


class Pipeline:
    def __init__(
        self,
        companies: list[Company],
        sources: Mapping[str, Source],
        store: Store,
        scorer: Scorer,
        notifier: Notifier,
        profile: Profile,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._companies = companies
        self._sources = sources
        self._store = store
        self._scorer = scorer
        self._notifier = notifier
        self._profile = profile
        self._clock = clock

    def run(self) -> RunReport:
        report = RunReport()
        self._collect(report)
        self._score(report)
        if self._notify(report):
            self._alert(report)
        return report

    def digest(self) -> int:
        thresholds = self._profile.thresholds
        jobs = self._store.due_digest(thresholds.digest, thresholds.immediate)
        if not jobs:
            return 0
        self._notifier.send(format_digest(jobs))
        self._store.mark_digested([s.job.id for s in jobs], self._clock())
        return len(jobs)

    def _collect(self, report: RunReport) -> None:
        now = self._clock()
        known = self._store.known_ids()
        for company in self._companies:
            if company.source == "none":
                continue
            source = self._sources.get(company.source)
            try:
                if source is None:
                    raise LookupError(f"unknown source '{company.source}'")
                jobs = source.fetch(company, known)
            except Exception as exc:  # one broken source must not stop the run
                log.warning("%s: %s", company.name, exc)
                report.errors.append(f"{company.name}: {exc}")
                self._store.record_source_result(company.name, str(exc), now)
                continue
            self._store.record_source_result(company.name, None, now)
            report.fetched += len(jobs)
            for job in jobs:
                if job.id in known:
                    continue
                known.add(job.id)
                if not prefilter.passes(job):
                    status = "rejected"
                elif job.source == "adzuna" and self._store.has_similar(
                    job.company, job.title
                ):
                    status = "duplicate"
                else:
                    status = "pending"
                self._store.add(job, status, now)
                report.new += 1
                report.candidates += status == "pending"

    def _score(self, report: RunReport) -> None:
        now = self._clock()
        limit = BATCH_SIZE * self._profile.max_llm_batches_per_run
        pending = self._store.pending(limit=limit)
        for start in range(0, len(pending), BATCH_SIZE):
            batch = pending[start : start + BATCH_SIZE]
            try:
                assessments = self._scorer.assess(batch)
            except LLMError as exc:
                log.warning("LLM unavailable: %s", exc)
                report.errors.append(f"LLM: {exc}")
                self._store.record_llm_result(False, now)
                return
            self._store.record_llm_result(True, now)
            missing = [job.id for job in batch if job.id not in assessments]
            self._store.record_attempt(missing)
            for job in batch:
                assessment = assessments.get(job.id)
                if assessment is None:
                    continue
                score = ranking.final_score(
                    job.tier, assessment, self._profile.weights
                )
                self._store.save_assessment(job.id, assessment, score)
                report.scored += 1

    def _notify(self, report: RunReport) -> bool:
        now = self._clock()
        due = self._store.due_immediate(
            self._profile.thresholds.immediate,
            limit=self._profile.max_immediate_per_run,
        )
        for scored in due:
            if not self._send(format_immediate(scored), report):
                return False
            self._store.mark_notified(scored.job.id, now)
            report.notified += 1
        return True

    def _alert(self, report: RunReport) -> None:
        now = self._clock()
        for company, error in self._store.sources_to_alert(now, SOURCE_ALERT_AFTER):
            if not self._send(format_source_alert(company, error), report):
                return
            self._store.mark_source_alerted(company)
        if self._store.llm_alert_due(now, LLM_ALERT_AFTER):
            if self._send(format_llm_alert(), report):
                self._store.mark_llm_alerted()

    def _send(self, message, report: RunReport) -> bool:
        try:
            self._notifier.send(message)
        except NotifyError as exc:
            log.warning("%s", exc)
            report.errors.append(str(exc))
            return False
        return True
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `poetry run pytest tests/test_pipeline.py -q`
Expected: all pass. If `test_source_alert_after_three_days` fails, check that `record_source_result` keeps `first_failure` from the first failure (the `ON CONFLICT` clause only updates `last_error`).

- [ ] **Step 5: Commit**

```bash
poetry run ruff check . && poetry run ruff format .
git add intern_radar/pipeline.py tests/test_pipeline.py
git commit -m "feat: add pipeline orchestrating collection, scoring and notifications"
```

---

### Task 10: CLI

**Files:**
- Create: `intern_radar/cli.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `config.load_profile`, `config.load_companies`, `config.ConfigError`, `sources.SOURCE_NAMES`, `sources.build_sources`, `http.make_client`, `store.Store`, `scorer.ClaudeCliBackend`, `scorer.Scorer`, `notifier.NtfyNotifier`, `notifier.ConsoleNotifier`, `notifier.NotifyError`, `pipeline.Pipeline`
- Produces: Typer `app` with commands `run [--dry-run]`, `digest [--dry-run]`, `list [--min-score N]`, `check-sources`; options `--config-dir` (default `config`), `--db` (default `data/intern-radar.db`); logs to `logs/intern-radar.log` and stderr.

- [ ] **Step 1: Failing tests `tests/test_cli.py`**

```python
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from intern_radar import cli
from intern_radar.sources.base import SourceError
from intern_radar.store import Store
from tests.factories import make_assessment, make_job

runner = CliRunner()

PROFILE = """candidate_summary: Student.
window_start: 2027-03-08
window_end: 2027-08-31
min_months: 4
ntfy_topic: t
"""
COMPANIES = """- {name: Acme, tier: A, source: greenhouse, board: acme}
- {name: Meta, tier: S, source: none}
- {name: Broken, tier: B, source: lever, site: broken}
"""


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / "config"
    directory.mkdir()
    (directory / "profile.yaml").write_text(PROFILE)
    (directory / "companies.yaml").write_text(COMPANIES)
    return directory


class OkSource:
    def fetch(self, company, known_ids):
        return [make_job(id="x")]


class BrokenSource:
    def fetch(self, company, known_ids):
        raise SourceError("HTTP 404")


def test_check_sources_reports_each_company(config_dir, monkeypatch):
    monkeypatch.setattr(cli, "build_sources", lambda client, companies, profile: {
        "greenhouse": OkSource(), "lever": BrokenSource()})
    result = runner.invoke(cli.app, ["check-sources"])
    assert result.exit_code == 1
    assert "OK    Acme" in result.output
    assert "1 internship offer(s)" in result.output
    assert "NONE  Meta" in result.output
    assert "FAIL  Broken" in result.output
    assert "HTTP 404" in result.output


def test_invalid_config_exits_with_message(config_dir):
    (config_dir / "companies.yaml").write_text("- {name: X, tier: Z, source: none}")
    result = runner.invoke(cli.app, ["check-sources"])
    assert result.exit_code == 2
    assert "invalid tier" in result.output


def test_list_prints_scored_jobs(config_dir):
    db = config_dir.parent / "data" / "intern-radar.db"
    db.parent.mkdir()
    store = Store(str(db))
    now = datetime(2026, 9, 24, tzinfo=UTC)
    store.add(make_job(id="a", title="ML Intern"), "pending", now)
    store.save_assessment("a", make_assessment(), 8.4)
    store.close()
    result = runner.invoke(cli.app, ["list", "--min-score", "5"])
    assert result.exit_code == 0
    assert "8.4  [A] Acme — ML Intern · London, UK" in result.output
    assert "https://example.com/jobs/1" in result.output


def test_run_dry_run_uses_console_notifier_and_memory_db(config_dir, monkeypatch):
    built = {}

    class FakePipeline:
        def __init__(self, companies, sources, store, scorer, notifier, profile):
            built["notifier"] = type(notifier).__name__

        def run(self):
            from intern_radar.pipeline import RunReport
            return RunReport(fetched=3, new=2, candidates=1, scored=1, notified=1)

    monkeypatch.setattr(cli, "Pipeline", FakePipeline)
    result = runner.invoke(cli.app, ["run", "--dry-run"])
    assert result.exit_code == 0
    assert built["notifier"] == "ConsoleNotifier"
    assert "fetched=3 new=2 candidates=1 scored=1 notified=1 errors=0" in result.output
    assert not (config_dir.parent / "data" / "intern-radar.db").exists()
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `poetry run pytest tests/test_cli.py -q`
Expected: FAIL with `ImportError: cannot import name 'cli'`.

- [ ] **Step 3: Write `intern_radar/cli.py`**

```python
"""Command-line entry point."""

import logging
from pathlib import Path

import typer

from intern_radar.config import ConfigError, load_companies, load_profile
from intern_radar.http import make_client
from intern_radar.notifier import ConsoleNotifier, NotifyError, NtfyNotifier
from intern_radar.pipeline import Pipeline
from intern_radar.scorer import ClaudeCliBackend, Scorer
from intern_radar.sources import SOURCE_NAMES, build_sources
from intern_radar.store import Store

app = typer.Typer(
    help="Watch top AI/tech companies for internship offers.",
    no_args_is_help=True,
)

LOG_PATH = Path("logs/intern-radar.log")
CONFIG_DIR = typer.Option(Path("config"), "--config-dir", help="Configuration dir.")
DB_PATH = typer.Option(Path("data/intern-radar.db"), "--db", help="SQLite file.")
DRY_RUN = typer.Option(False, "--dry-run", help="Print instead of notifying.")


def _setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def _load(config_dir: Path):
    try:
        profile = load_profile(config_dir / "profile.yaml")
        companies = load_companies(config_dir / "companies.yaml", SOURCE_NAMES)
    except ConfigError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(2) from exc
    return profile, companies


def _open_store(db: Path, dry_run: bool) -> Store:
    if dry_run:
        return Store(":memory:")
    db.parent.mkdir(parents=True, exist_ok=True)
    return Store(str(db))


def _pipeline(config_dir: Path, db: Path, dry_run: bool):
    profile, companies = _load(config_dir)
    client = make_client()
    store = _open_store(db, dry_run)
    scorer = Scorer(
        ClaudeCliBackend(model=profile.llm_model),
        profile.candidate_summary,
        profile.window_start,
        profile.window_end,
        profile.min_months,
    )
    notifier = (
        ConsoleNotifier()
        if dry_run
        else NtfyNotifier(profile.ntfy_server, profile.ntfy_topic, client)
    )
    sources = build_sources(client, companies, profile)
    pipeline = Pipeline(companies, sources, store, scorer, notifier, profile)
    return pipeline, store, client


@app.command()
def run(
    dry_run: bool = DRY_RUN, config_dir: Path = CONFIG_DIR, db: Path = DB_PATH
) -> None:
    """Fetch, filter, score and notify new internship offers."""
    _setup_logging()
    pipeline, store, client = _pipeline(config_dir, db, dry_run)
    try:
        report = pipeline.run()
    finally:
        store.close()
        client.close()
    typer.echo(
        f"fetched={report.fetched} new={report.new} candidates={report.candidates}"
        f" scored={report.scored} notified={report.notified}"
        f" errors={len(report.errors)}"
    )


@app.command()
def digest(
    dry_run: bool = DRY_RUN, config_dir: Path = CONFIG_DIR, db: Path = DB_PATH
) -> None:
    """Send the evening digest of mid-score offers."""
    _setup_logging()
    pipeline, store, client = _pipeline(config_dir, db, dry_run)
    try:
        count = pipeline.digest()
    except NotifyError as exc:
        typer.echo(f"Digest not sent: {exc}", err=True)
        raise typer.Exit(1) from exc
    finally:
        store.close()
        client.close()
    typer.echo(f"digest: {count} offer(s)")


@app.command("list")
def list_jobs(
    min_score: float = typer.Option(0.0, "--min-score"), db: Path = DB_PATH
) -> None:
    """Print stored offers, best first."""
    store = Store(str(db))
    try:
        for scored in store.scored(min_score):
            job = scored.job
            typer.echo(
                f"{scored.score:4.1f}  [{job.tier}] {job.company} — {job.title}"
                f" · {job.location}\n      {job.url}"
            )
    finally:
        store.close()


@app.command("check-sources")
def check_sources(config_dir: Path = CONFIG_DIR) -> None:
    """Fetch every company once and report which ones are covered."""
    profile, companies = _load(config_dir)
    client = make_client()
    sources = build_sources(client, companies, profile)
    failures = 0
    try:
        for company in companies:
            label = f"{company.name:<24} {company.source:<16}"
            if company.source == "none":
                typer.echo(f"NONE  {label} no feed, covered by Adzuna only")
                continue
            try:
                jobs = sources[company.source].fetch(company, set())
            except Exception as exc:  # report every failure, keep going
                failures += 1
                typer.echo(f"FAIL  {label} {exc}")
                continue
            typer.echo(f"OK    {label} {len(jobs)} internship offer(s)")
    finally:
        client.close()
    if failures:
        raise typer.Exit(1)
```

- [ ] **Step 4: Run the whole suite**

Run: `poetry run pytest -q`
Expected: all pass.

- [ ] **Step 5: Manual smoke test against real APIs**

```bash
cp config/profile.example.yaml config/profile.yaml
poetry run intern-radar check-sources
poetry run intern-radar run --dry-run
```

Expected: `check-sources` prints `OK` for Anthropic, OpenAI, Palantir; `run --dry-run` prints the notifications it would send and a summary line.

- [ ] **Step 6: Commit and open the milestone 4 PR**

```bash
poetry run ruff check . && poetry run ruff format .
git add intern_radar/cli.py tests/test_cli.py
git commit -m "feat: add command-line interface"
git fetch origin && git rebase origin/develop && poetry run pytest -q
git push -u origin feature/4-notifications-cli
gh pr create --base develop --title "feat: ntfy notifications, pipeline and CLI" --body "Milestone 4: ntfy notifier, pipeline (collection, pre-filter, batched scoring with caps and retries, immediate notifications, source and LLM health alerts, evening digest) and the run/digest/list/check-sources commands.

Tests: \`poetry run pytest -q\` passes; \`check-sources\` and \`run --dry-run\` checked against real APIs.

Closes #4"
```

After the merge: `git switch develop && git pull --ff-only && git switch -c feature/5-portals-adzuna`.

---

### Task 11: Workday, Amazon and Microsoft plugins

**Files:**
- Create: `intern_radar/sources/workday.py`, `intern_radar/sources/amazon.py`, `intern_radar/sources/microsoft.py`, `tests/sources/test_workday.py`, `tests/sources/test_amazon.py`, `tests/sources/test_microsoft.py`
- Modify: `intern_radar/sources/__init__.py`

**Interfaces:**
- Produces: `WorkdaySource(client)` (params `host`, `tenant`, `site`), `AmazonSource(client)`, `MicrosoftSource(client)` (no params); `SOURCE_NAMES` and `build_sources` gain `workday`, `amazon`, `microsoft`.

- [ ] **Step 1: Failing test `tests/sources/test_workday.py`**

```python
import json

import httpx

from intern_radar.models import Company, Job
from intern_radar.sources.workday import WorkdaySource
from tests.factories import mock_client

BASE = "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite"
COMPANY = Company("NVIDIA", "S", "workday", {
    "host": "nvidia.wd5.myworkdayjobs.com", "tenant": "nvidia",
    "site": "NVIDIAExternalCareerSite"})


def search(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    assert body["searchText"] == "intern" and body["limit"] == 20
    if body["offset"] == 0:
        postings = [{"title": f"Other Role {i}", "externalPath": f"/job/x/{i}"}
                    for i in range(19)]
        postings.append({"title": "Deep Learning Intern - 2027",
                         "externalPath": "/job/UK-Reading/DL-Intern_JR1"})
        return httpx.Response(200, json={"total": 21, "jobPostings": postings})
    return httpx.Response(200, json={"total": 0, "jobPostings": [
        {"externalPath": "/job/x/untitled"},
        {"title": "Hardware Intern", "externalPath": "/job/x/known"},
    ]})


DETAIL = {"jobPostingInfo": {
    "title": "Deep Learning Intern - 2027", "jobReqId": "JR1",
    "location": "UK, Reading", "startDate": "2026-09-16",
    "jobDescription": "<p>Train LLMs.</p>",
    "externalUrl": "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/DL-Intern_JR1",
}}


def test_fetch_pages_with_first_page_total_and_reads_details():
    client = mock_client({f"POST {BASE}/jobs": search,
                          f"GET {BASE}/job/UK-Reading/DL-Intern_JR1": DETAIL})
    jobs = WorkdaySource(client).fetch(
        COMPANY, known_ids={"workday:nvidia:/job/x/known"})
    assert jobs == [Job(
        id="workday:nvidia:/job/UK-Reading/DL-Intern_JR1",
        company="NVIDIA", tier="S", title="Deep Learning Intern - 2027",
        location="UK, Reading",
        url="https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/DL-Intern_JR1",
        description="Train LLMs.", source="workday", posted_at="2026-09-16")]
```

- [ ] **Step 2: `intern_radar/sources/workday.py`**

```python
"""Workday career sites (the cxs JSON API behind *.myworkdayjobs.com)."""

from collections.abc import Container

import httpx

from intern_radar.models import Company, Job
from intern_radar.prefilter import is_internship_title
from intern_radar.sources.base import get_json, html_to_text, require_param

PAGE_SIZE = 20
MAX_PAGES = 5  # results are relevance-sorted; internships come first


class WorkdaySource:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def fetch(self, company: Company, known_ids: Container[str]) -> list[Job]:
        host = require_param(company, "host")
        tenant = require_param(company, "tenant")
        site = require_param(company, "site")
        base = f"https://{host}/wday/cxs/{tenant}/{site}"
        jobs: list[Job] = []
        total = 0
        for page in range(MAX_PAGES):
            data = get_json(
                self._client,
                "POST",
                f"{base}/jobs",
                json={
                    "appliedFacets": {},
                    "limit": PAGE_SIZE,
                    "offset": page * PAGE_SIZE,
                    "searchText": "intern",
                },
            )
            if page == 0:  # Workday only reports the total on the first page
                total = data.get("total", 0)
            postings = data.get("jobPostings", [])
            for posting in postings:
                title = posting.get("title")
                path = posting.get("externalPath")
                if not title or not path or not is_internship_title(title):
                    continue
                job_id = f"workday:{tenant}:{path}"
                if job_id in known_ids:
                    continue
                info = get_json(self._client, "GET", f"{base}{path}")[
                    "jobPostingInfo"
                ]
                jobs.append(
                    Job(
                        id=job_id,
                        company=company.name,
                        tier=company.tier,
                        title=title.strip(),
                        location=info.get("location")
                        or posting.get("locationsText", ""),
                        url=info.get("externalUrl") or f"https://{host}/{site}{path}",
                        description=html_to_text(info.get("jobDescription") or ""),
                        source="workday",
                        posted_at=info.get("startDate"),
                    )
                )
            if len(postings) < PAGE_SIZE or (page + 1) * PAGE_SIZE >= total:
                break
        return jobs
```

Run: `poetry run pytest tests/sources/test_workday.py -q` → pass.

- [ ] **Step 3: Failing test `tests/sources/test_amazon.py`**

```python
import httpx

from intern_radar.models import Company, Job
from intern_radar.sources.amazon import AmazonSource
from tests.factories import mock_client

API = "https://www.amazon.jobs/en/search.json"
COMPANY = Company("Amazon", "S", "amazon", {})


def search(request: httpx.Request) -> httpx.Response:
    assert request.url.params["base_query"] == "intern"
    offset = int(request.url.params["offset"])
    jobs = [] if offset else [
        {"id_icims": "10512549", "title": "Applied Scientist Intern",
         "normalized_location": "London, GBR",
         "job_path": "/en/jobs/10512549/applied-scientist-intern",
         "posted_date": "August 24, 2026",
         "description": "Research on LLMs.<br/>6 months.",
         "basic_qualifications": "- Enrolled in a Master's degree",
         "preferred_qualifications": ""},
        {"id_icims": "2", "title": "Area Manager", "normalized_location": "X",
         "job_path": "/en/jobs/2/area-manager", "posted_date": "bad date",
         "description": "", "basic_qualifications": "",
         "preferred_qualifications": ""},
    ]
    return httpx.Response(200, json={"hits": 2, "jobs": jobs})


def test_fetch_maps_amazon_jobs():
    jobs = AmazonSource(mock_client({f"GET {API}": search})).fetch(COMPANY, set())
    assert jobs == [Job(
        id="amazon:10512549", company="Amazon", tier="S",
        title="Applied Scientist Intern", location="London, GBR",
        url="https://www.amazon.jobs/en/jobs/10512549/applied-scientist-intern",
        description="Research on LLMs.\n6 months.\n- Enrolled in a Master's degree",
        source="amazon", posted_at="2026-08-24")]
```

- [ ] **Step 4: `intern_radar/sources/amazon.py`**

```python
"""amazon.jobs search API."""

from collections.abc import Container
from datetime import datetime

import httpx

from intern_radar.models import Company, Job
from intern_radar.prefilter import is_internship_title
from intern_radar.sources.base import get_json, html_to_text

API = "https://www.amazon.jobs/en/search.json"
PAGE_SIZE = 100
MAX_PAGES = 5


def _posted(value: str | None) -> str | None:
    try:
        return datetime.strptime(value or "", "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


class AmazonSource:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def fetch(self, company: Company, known_ids: Container[str]) -> list[Job]:
        jobs: list[Job] = []
        for page in range(MAX_PAGES):
            offset = page * PAGE_SIZE
            data = get_json(
                self._client,
                "GET",
                API,
                params={
                    "base_query": "intern",
                    "result_limit": PAGE_SIZE,
                    "offset": offset,
                    "sort": "recent",
                },
            )
            items = data.get("jobs", [])
            for item in items:
                job_id = f"amazon:{item['id_icims']}"
                if job_id in known_ids or not is_internship_title(item["title"]):
                    continue
                parts = (
                    item.get("description", ""),
                    item.get("basic_qualifications", ""),
                    item.get("preferred_qualifications", ""),
                )
                jobs.append(
                    Job(
                        id=job_id,
                        company=company.name,
                        tier=company.tier,
                        title=item["title"].strip(),
                        location=item.get("normalized_location")
                        or item.get("location", ""),
                        url=f"https://www.amazon.jobs{item['job_path']}",
                        description=html_to_text("<br/>".join(p for p in parts if p)),
                        source="amazon",
                        posted_at=_posted(item.get("posted_date")),
                    )
                )
            if len(items) < PAGE_SIZE or offset + PAGE_SIZE >= data.get("hits", 0):
                break
        return jobs
```

Run: `poetry run pytest tests/sources/test_amazon.py -q` → pass.

- [ ] **Step 5: Failing test `tests/sources/test_microsoft.py`**

```python
import httpx

from intern_radar.models import Company, Job
from intern_radar.sources.microsoft import MicrosoftSource
from tests.factories import mock_client

API = "https://apply.careers.microsoft.com/api/pcsx/search"
COMPANY = Company("Microsoft", "S", "microsoft", {})


def search(request: httpx.Request) -> httpx.Response:
    start = int(request.url.params["start"])
    positions = [] if start else [
        {"id": 1970393556917520, "name": "Data Science INTERN",
         "locations": ["United Kingdom, London", "Ireland, Dublin"],
         "postedTs": 1789031303, "positionUrl": "/careers/job/1970393556917520"},
        {"id": 7, "name": "Account Executive", "locations": ["US"],
         "postedTs": 1789031303, "positionUrl": "/careers/job/7"},
    ]
    return httpx.Response(200, json={"status": 200,
                                     "data": {"positions": positions}})


def test_fetch_maps_microsoft_positions():
    jobs = MicrosoftSource(mock_client({f"GET {API}": search})).fetch(COMPANY, set())
    assert jobs == [Job(
        id="microsoft:1970393556917520", company="Microsoft", tier="S",
        title="Data Science INTERN",
        location="United Kingdom, London; Ireland, Dublin",
        url="https://apply.careers.microsoft.com/careers/job/1970393556917520",
        description="", source="microsoft", posted_at="2026-09-10")]
```

(`1789031303` s = 2026-09-10 UTC. The search API returns no description; the LLM scores Microsoft offers from title and location.)

- [ ] **Step 6: `intern_radar/sources/microsoft.py`**

```python
"""Microsoft careers search API (apply.careers.microsoft.com)."""

from collections.abc import Container
from datetime import UTC, datetime

import httpx

from intern_radar.models import Company, Job
from intern_radar.prefilter import is_internship_title
from intern_radar.sources.base import get_json

API = "https://apply.careers.microsoft.com/api/pcsx/search"
SITE = "https://apply.careers.microsoft.com"
MAX_PAGES = 10


class MicrosoftSource:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def fetch(self, company: Company, known_ids: Container[str]) -> list[Job]:
        jobs: list[Job] = []
        start = 0
        for _ in range(MAX_PAGES):
            data = get_json(
                self._client,
                "GET",
                API,
                params={"domain": "microsoft.com", "query": "intern", "start": start},
            )
            positions = (data.get("data") or {}).get("positions", [])
            if not positions:
                break
            for item in positions:
                job_id = f"microsoft:{item['id']}"
                if job_id in known_ids or not is_internship_title(item["name"]):
                    continue
                posted = item.get("postedTs")
                jobs.append(
                    Job(
                        id=job_id,
                        company=company.name,
                        tier=company.tier,
                        title=item["name"].strip(),
                        location="; ".join(item.get("locations") or []),
                        url=f"{SITE}{item['positionUrl']}",
                        description="",
                        source="microsoft",
                        posted_at=(
                            datetime.fromtimestamp(posted, UTC).date().isoformat()
                            if posted
                            else None
                        ),
                    )
                )
            start += len(positions)
        return jobs
```

Run: `poetry run pytest tests/sources/test_microsoft.py -q` → pass.

- [ ] **Step 7: Register the plugins**

In `intern_radar/sources/__init__.py` add the imports

```python
from intern_radar.sources.amazon import AmazonSource
from intern_radar.sources.microsoft import MicrosoftSource
from intern_radar.sources.workday import WorkdaySource
```

extend `SOURCE_NAMES` with `"workday", "amazon", "microsoft"`, and add to the dict returned by `build_sources`:

```python
        "workday": WorkdaySource(client),
        "amazon": AmazonSource(client),
        "microsoft": MicrosoftSource(client),
```

Run: `poetry run pytest -q` → all pass (the registry test checks the names).

- [ ] **Step 8: Commit**

```bash
poetry run ruff check . && poetry run ruff format .
git add intern_radar/sources tests/sources
git commit -m "feat: add Workday, Amazon and Microsoft sources"
```

---

### Task 12: Adzuna plugin

**Files:**
- Create: `intern_radar/sources/adzuna.py`, `tests/sources/test_adzuna.py`
- Modify: `intern_radar/sources/__init__.py`

**Interfaces:**
- Consumes: `Company.params["aliases"]` (optional list of extra names), `Profile.adzuna_app_id`, `Profile.adzuna_app_key`
- Produces:
  - `adzuna.DEFAULT_COUNTRIES = ("gb", "us", "ca", "sg", "de", "nl", "ch", "es", "it", "at", "be", "pl")`
  - `adzuna.company_lookup(companies: list[Company]) -> dict[str, tuple[str, Tier]]` (lower-cased name or alias → canonical name, tier; `unlisted` companies ignored)
  - `adzuna.match_company(employer: str, lookup: dict[str, tuple[str, Tier]]) -> tuple[str, Tier]`
  - `adzuna.AdzunaSource(client, app_id: str | None, app_key: str | None, lookup: dict[str, tuple[str, Tier]])` (param `countries`, optional)

- [ ] **Step 1: Failing tests `tests/sources/test_adzuna.py`**

```python
import httpx
import pytest

from intern_radar.models import Company, Job
from intern_radar.sources.adzuna import AdzunaSource, company_lookup, match_company
from intern_radar.sources.base import SourceError
from tests.factories import mock_client

COMPANIES = [
    Company("Google", "S", "none", {"aliases": ["DeepMind"]}),
    Company("Apple", "S", "none", {}),
    Company("Adzuna", "unlisted", "adzuna", {"countries": ["gb"]}),
]
LOOKUP = company_lookup(COMPANIES)


@pytest.mark.parametrize(
    "employer, expected",
    [
        ("Google UK Ltd", ("Google", "S")),
        ("DeepMind Technologies", ("Google", "S")),
        ("Applebee's", ("Applebee's", "unlisted")),
        ("", ("Unknown employer", "unlisted")),
    ],
)
def test_match_company(employer, expected):
    assert match_company(employer, LOOKUP) == expected


def search(request: httpx.Request) -> httpx.Response:
    params = request.url.params
    assert (params["app_id"], params["app_key"]) == ("id", "key")
    assert params["what"] == "intern"
    return httpx.Response(200, json={"results": [
        {"id": "555", "title": "<strong>AI</strong> Research Intern",
         "company": {"display_name": "Google UK Ltd"},
         "location": {"display_name": "London, UK"},
         "redirect_url": "https://www.adzuna.co.uk/jobs/land/ad/555",
         "description": "Gemini research...", "created": "2026-09-20T10:00:00Z"},
        {"id": "556", "title": "Sales Manager", "company": {"display_name": "X"},
         "location": {"display_name": "London"},
         "redirect_url": "https://a/556", "description": "", "created": None},
    ]})


def test_fetch_maps_results_and_attributes_listed_companies():
    client = mock_client({"GET https://api.adzuna.com/v1/api/jobs/gb/search/1": search})
    source = AdzunaSource(client, "id", "key", LOOKUP)
    assert source.fetch(COMPANIES[2], set()) == [Job(
        id="adzuna:555", company="Google", tier="S", title="AI Research Intern",
        location="London, UK", url="https://www.adzuna.co.uk/jobs/land/ad/555",
        description="Gemini research...", source="adzuna", posted_at="2026-09-20")]


def test_fetch_requires_keys():
    source = AdzunaSource(mock_client({}), None, None, LOOKUP)
    with pytest.raises(SourceError, match="adzuna_app_id"):
        source.fetch(COMPANIES[2], set())
```

- [ ] **Step 2: `intern_radar/sources/adzuna.py`**

```python
"""Adzuna job search API, a catch-all for companies without a usable feed."""

import re
from collections.abc import Container

import httpx

from intern_radar.models import Company, Job, Tier
from intern_radar.prefilter import is_internship_title
from intern_radar.sources.base import SourceError, get_json, html_to_text, iso_date

API = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"
DEFAULT_COUNTRIES = ("gb", "us", "ca", "sg", "de", "nl", "ch", "es", "it", "at",
                     "be", "pl")

Lookup = dict[str, tuple[str, Tier]]


def company_lookup(companies: list[Company]) -> Lookup:
    lookup: Lookup = {}
    for company in companies:
        if company.tier == "unlisted":
            continue
        for name in [company.name, *company.params.get("aliases", [])]:
            lookup[name.lower()] = (company.name, company.tier)
    return lookup


def match_company(employer: str, lookup: Lookup) -> tuple[str, Tier]:
    lowered = employer.lower()
    for name, match in lookup.items():
        if re.search(rf"\b{re.escape(name)}\b", lowered):
            return match
    return (employer or "Unknown employer", "unlisted")


class AdzunaSource:
    def __init__(
        self,
        client: httpx.Client,
        app_id: str | None,
        app_key: str | None,
        lookup: Lookup,
    ) -> None:
        self._client = client
        self._app_id = app_id
        self._app_key = app_key
        self._lookup = lookup

    def fetch(self, company: Company, known_ids: Container[str]) -> list[Job]:
        if not (self._app_id and self._app_key):
            raise SourceError("adzuna_app_id / adzuna_app_key missing in profile.yaml")
        jobs: list[Job] = []
        for country in company.params.get("countries", DEFAULT_COUNTRIES):
            data = get_json(
                self._client,
                "GET",
                API.format(country=country),
                params={
                    "app_id": self._app_id,
                    "app_key": self._app_key,
                    "results_per_page": 50,
                    "what": "intern",
                    "what_or": "machine learning ai data llm",
                    "max_days_old": 7,
                    "sort_by": "date",
                    "content-type": "application/json",
                },
            )
            for item in data.get("results", []):
                job_id = f"adzuna:{item['id']}"
                title = html_to_text(item.get("title", ""))
                if job_id in known_ids or not is_internship_title(title):
                    continue
                employer = (item.get("company") or {}).get("display_name", "")
                name, tier = match_company(employer, self._lookup)
                jobs.append(
                    Job(
                        id=job_id,
                        company=name,
                        tier=tier,
                        title=title,
                        location=(item.get("location") or {}).get("display_name", ""),
                        url=item["redirect_url"],
                        description=html_to_text(item.get("description", "")),
                        source="adzuna",
                        posted_at=iso_date(item.get("created")),
                    )
                )
        return jobs
```

Run: `poetry run pytest tests/sources/test_adzuna.py -q` → pass.

- [ ] **Step 3: Register Adzuna**

In `intern_radar/sources/__init__.py`: import `from intern_radar.sources.adzuna import AdzunaSource, company_lookup`, add `"adzuna"` to `SOURCE_NAMES`, and add to the `build_sources` dict:

```python
        "adzuna": AdzunaSource(
            client,
            profile.adzuna_app_id,
            profile.adzuna_app_key,
            company_lookup(companies),
        ),
```

Remove the note about unused arguments. Run: `poetry run pytest -q` → all pass.

- [ ] **Step 4: Commit and open the milestone 5 PR**

```bash
poetry run ruff check . && poetry run ruff format .
git add intern_radar/sources tests/sources
git commit -m "feat: add Adzuna source with company attribution"
git fetch origin && git rebase origin/develop && poetry run pytest -q
git push -u origin feature/5-portals-adzuna
gh pr create --base develop --title "feat: Workday, Amazon, Microsoft and Adzuna sources" --body "Milestone 5: Workday cxs API (first-page total, detail per internship), amazon.jobs and Microsoft careers search, Adzuna catch-all with attribution to listed companies and aliases.

Tests: \`poetry run pytest -q\` passes.

Closes #5"
```

After the merge: `git switch develop && git pull --ff-only && git switch -c feature/6-deployment`.

---

### Task 13: Verified company list

**Files:**
- Modify: `config/companies.yaml`

- [ ] **Step 1: Write the full list**

Entries marked ✅ were verified on 2026-09-24; the others must pass `check-sources` in Step 2.

```yaml
# Tier S
- {name: Google, tier: S, source: none, aliases: [DeepMind, Google DeepMind]}
- {name: Meta, tier: S, source: none, aliases: [Facebook]}
- {name: Apple, tier: S, source: none}
- {name: Microsoft, tier: S, source: microsoft}                    # ✅
- {name: Amazon, tier: S, source: amazon, aliases: [AWS, Amazon Web Services]}  # ✅
- {name: NVIDIA, tier: S, source: workday, host: nvidia.wd5.myworkdayjobs.com, tenant: nvidia, site: NVIDIAExternalCareerSite}  # ✅
- {name: OpenAI, tier: S, source: ashby, org: openai}               # ✅
- {name: Anthropic, tier: S, source: greenhouse, board: anthropic}  # ✅
# Tier A — AI and tech
- {name: Mistral AI, tier: A, source: none, aliases: [Mistral]}
- {name: Cohere, tier: A, source: ashby, org: cohere}               # ✅
- {name: Databricks, tier: A, source: greenhouse, board: databricks}  # ✅
- {name: Scale AI, tier: A, source: greenhouse, board: scaleai}     # ✅
- {name: Hugging Face, tier: A, source: workable, account: huggingface}  # ✅
- {name: Stripe, tier: A, source: greenhouse, board: stripe}        # ✅
- {name: Palantir, tier: A, source: lever, site: palantir}          # ✅
- {name: Perplexity, tier: A, source: ashby, org: perplexity}       # ✅
- {name: xAI, tier: A, source: greenhouse, board: xai}              # ✅
- {name: Tesla, tier: A, source: none}
- {name: ByteDance, tier: A, source: none, aliases: [TikTok]}
- {name: IBM, tier: A, source: none}
- {name: Salesforce, tier: A, source: workday, host: salesforce.wd12.myworkdayjobs.com, tenant: salesforce, site: External_Career_Site}  # ✅
- {name: Adobe, tier: A, source: workday, host: adobe.wd5.myworkdayjobs.com, tenant: adobe, site: external_experienced}  # ✅
- {name: Intel, tier: A, source: workday, host: intel.wd1.myworkdayjobs.com, tenant: intel, site: External}  # ✅
- {name: Samsung, tier: A, source: workday, host: sec.wd3.myworkdayjobs.com, tenant: sec, site: Samsung_Careers}  # ✅
# Tier A — finance and quant
- {name: Jane Street, tier: A, source: greenhouse, board: janestreet}  # ✅
- {name: Citadel, tier: A, source: none, aliases: [Citadel Securities]}
- {name: Two Sigma, tier: A, source: none}
- {name: Goldman Sachs, tier: A, source: none}
- {name: JPMorgan Chase, tier: A, source: none, aliases: [JP Morgan, J.P. Morgan, JPMorgan]}
- {name: Point72, tier: A, source: greenhouse, board: point72}      # ✅
- {name: DRW, tier: A, source: greenhouse, board: drweng}           # ✅
- {name: IMC Trading, tier: A, source: greenhouse, board: imc}      # ✅
- {name: XTX Markets, tier: A, source: greenhouse, board: xtxmarketstechnologies}  # ✅
- {name: Citi, tier: A, source: workday, host: citi.wd5.myworkdayjobs.com, tenant: citi, site: "2"}  # ✅
- {name: BlackRock, tier: A, source: workday, host: blackrock.wd1.myworkdayjobs.com, tenant: blackrock, site: BlackRock_Professional}  # ✅
# Tier A — consulting
- {name: McKinsey, tier: A, source: none, aliases: [QuantumBlack]}
- {name: BCG, tier: A, source: none, aliases: [Boston Consulting Group, BCG X]}
# Tier B
- {name: Snowflake, tier: B, source: ashby, org: snowflake}         # ✅
- {name: Datadog, tier: B, source: greenhouse, board: datadog}      # ✅
- {name: Figma, tier: B, source: greenhouse, board: figma}          # ✅
- {name: Cloudflare, tier: B, source: greenhouse, board: cloudflare}  # ✅
- {name: Airbnb, tier: B, source: greenhouse, board: airbnb}        # ✅
- {name: Pinterest, tier: B, source: greenhouse, board: pinterest}  # ✅
- {name: Reddit, tier: B, source: greenhouse, board: reddit}        # ✅
- {name: Waymo, tier: B, source: greenhouse, board: waymo}          # ✅
- {name: Coinbase, tier: B, source: greenhouse, board: coinbase}    # ✅
- {name: Robinhood, tier: B, source: greenhouse, board: robinhood}  # ✅
- {name: Samsara, tier: B, source: greenhouse, board: samsara}      # ✅
- {name: Spotify, tier: B, source: lever, site: spotify}            # ✅
- {name: Uber, tier: B, source: none}
- {name: Qualcomm, tier: B, source: none}
- {name: DeepL, tier: B, source: ashby, org: deepl}                 # ✅
- {name: ElevenLabs, tier: B, source: ashby, org: elevenlabs}       # ✅
- {name: Synthesia, tier: B, source: ashby, org: synthesia}         # ✅
- {name: Wayve, tier: B, source: greenhouse, board: wayve}          # ✅
- {name: Helsing, tier: B, source: greenhouse, board: helsing}      # ✅
- {name: Canva, tier: B, source: smartrecruiters, company_id: Canva}  # ✅
- {name: Bosch, tier: B, source: smartrecruiters, company_id: BoschGroup}  # ✅
- {name: Mastercard, tier: B, source: workday, host: mastercard.wd1.myworkdayjobs.com, tenant: mastercard, site: CorporateCareers}  # ✅
- {name: Accenture, tier: B, source: workday, host: accenture.wd103.myworkdayjobs.com, tenant: accenture, site: AccentureCareers}  # ✅
- {name: Airbus, tier: B, source: workday, host: ag.wd3.myworkdayjobs.com, tenant: ag, site: Airbus}  # ✅
- {name: Siemens, tier: B, source: none}
- {name: Grab, tier: B, source: none}
- {name: Sea, tier: B, source: none, aliases: [Shopee, Garena]}
- {name: Shopify, tier: B, source: none}
# Catch-all
- {name: Adzuna, tier: unlisted, source: adzuna}
```

- [ ] **Step 2: Verify against the real APIs**

Run: `poetry run intern-radar check-sources`
Expected: `OK` for every company with a source, `NONE` for the `source: none` ones. For each `FAIL`, open the company's careers page in a browser, find the job board used in the page links (`boards.greenhouse.io/<board>`, `jobs.lever.co/<site>`, `jobs.ashbyhq.com/<org>`, `apply.workable.com/<account>`, `jobs.smartrecruiters.com/<id>`, `<host>/<site>` for Workday) and fix the entry; if no public board exists, set `source: none`. The Adzuna line fails until the keys are in `profile.yaml` (Task 14).

- [ ] **Step 3: Commit**

```bash
git add config/companies.yaml
git commit -m "feat: add verified list of watched companies"
```

---

### Task 14: Deployment on the VPS

**Files:**
- Create: `deploy/intern-radar-run.service`, `deploy/intern-radar-run.timer`, `deploy/intern-radar-digest.service`, `deploy/intern-radar-digest.timer`, `deploy/logrotate.conf`
- Modify: `README.md`

- [ ] **Step 1: systemd units**

`deploy/intern-radar-run.service`:

```ini
[Unit]
Description=intern-radar: fetch, score and notify internship offers
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/root/remote-claude/intern-radar
Environment=HOME=/root
Environment=PATH=/root/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/root/.local/bin/poetry run intern-radar run
TimeoutStartSec=1h
```

`deploy/intern-radar-run.timer`:

```ini
[Unit]
Description=Run intern-radar every 2 hours from 08:00 to 22:00 Paris time

[Timer]
OnCalendar=*-*-* 08,10,12,14,16,18,20,22:00:00 Europe/Paris
Persistent=true

[Install]
WantedBy=timers.target
```

`deploy/intern-radar-digest.service`:

```ini
[Unit]
Description=intern-radar: evening digest
After=network-online.target intern-radar-run.service
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/root/remote-claude/intern-radar
Environment=HOME=/root
Environment=PATH=/root/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/root/.local/bin/poetry run intern-radar digest
```

`deploy/intern-radar-digest.timer`:

```ini
[Unit]
Description=Send the intern-radar digest at 21:00 Paris time

[Timer]
OnCalendar=*-*-* 21:00:00 Europe/Paris
Persistent=true

[Install]
WantedBy=timers.target
```

`deploy/logrotate.conf`:

```
/root/remote-claude/intern-radar/logs/*.log {
    weekly
    rotate 8
    compress
    missingok
    notifempty
    copytruncate
}
```

- [ ] **Step 2: README**

Replace `README.md` with: a one-paragraph description (from the spec goal); a "How it works" list (sources → pre-filter → LLM scoring → final score → ntfy); "Setup" (`poetry install`, copy `config/profile.example.yaml` to `config/profile.yaml`, pick a long random ntfy topic with `python -c "import secrets; print('intern-radar-' + secrets.token_urlsafe(16))"`, subscribe to it in the ntfy app, free Adzuna keys, `claude` CLI logged in); "Usage" (the four commands); "Deployment" (the commands of Step 4); "Tests" (`poetry run pytest -q`); license MIT.

- [ ] **Step 3: Commit and open the milestone 6 PR**

```bash
git add deploy README.md
git commit -m "docs: add systemd deployment and usage documentation"
git fetch origin && git rebase origin/develop && poetry run pytest -q
git push -u origin feature/6-deployment
gh pr create --base develop --title "feat: verified company list and VPS deployment" --body "Milestone 6: 70 companies across tiers S/A/B with verified sources, systemd timers (Europe/Paris), logrotate, README.

Tests: \`poetry run pytest -q\` passes; \`check-sources\` output attached below.

Closes #6"
```

Paste the `check-sources` output in a PR comment.

- [ ] **Step 4: Install on the VPS (after the merge, from `develop`)**

```bash
cd /root/remote-claude/intern-radar
git switch develop && git pull --ff-only
poetry install --only main
# config/profile.yaml: real ntfy topic and Adzuna keys, filled by the user
ln -sf "$PWD/deploy/intern-radar-run.service" "$PWD/deploy/intern-radar-run.timer" \
       "$PWD/deploy/intern-radar-digest.service" "$PWD/deploy/intern-radar-digest.timer" \
       /etc/systemd/system/
cp deploy/logrotate.conf /etc/logrotate.d/intern-radar
systemctl daemon-reload
systemctl enable --now intern-radar-run.timer intern-radar-digest.timer
systemctl start intern-radar-run.service
```

- [ ] **Step 5: Verify the deployment**

```bash
systemctl list-timers 'intern-radar*'
journalctl -u intern-radar-run.service -n 30 --no-pager
poetry run intern-radar list --min-score 0 | head -20
```

Expected: both timers listed with their next run in Paris time; the service log ends with a `fetched=… new=… candidates=… scored=… notified=… errors=…` line; `list` shows scored offers; high-score offers arrived on the phone through ntfy.

- [ ] **Step 6: Release 0.1.0**

```bash
git switch -c release/0.1.0 develop
git push -u origin release/0.1.0
gh pr create --base main --title "chore(release): 0.1.0" --body "First release: watches 70 companies, LLM scoring, ntfy notifications, deployed with systemd timers."
```

After the user merges: `git fetch origin && git tag -a v0.1.0 origin/main -m "v0.1.0" && git push origin v0.1.0 && git switch develop && git merge --ff-only origin/main && git push origin develop`.
