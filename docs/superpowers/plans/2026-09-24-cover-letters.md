# Cover Letters on Demand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One tap on an offer notification produces a tailored, checked cover letter as a simple PDF, delivered through ntfy and Gmail.

**Architecture:** Offer notifications gain an ntfy HTTP action that posts the job id to a second secret topic. A systemd service streams that topic (outbound connection only), and for each request: loads the job from SQLite, reads the CV (Google Doc PDF export, cached), writes the letter with the LLM CLI (draft → ATS revision → anti-AI rewrite), runs pure Python checks (keyword coverage, blacklist, fidelity), renders a PDF with fpdf2 and delivers it (ntfy attachment + Gmail SMTP).

**Tech Stack:** Python ≥ 3.12, httpx, fpdf2 (PDF), pypdf (CV text), smtplib (stdlib), sqlite3, pytest.

**Spec:** `docs/superpowers/specs/2026-09-24-cover-letters-design.md`

## Global Constraints

- Letters use only facts from the CV text; `not_in_cv` keywords are never added.
- LLM calls go through `ClaudeCliBackend(model=profile.letter_model)` (default `sonnet`); scoring keeps `haiku`.
- PDF: A4, 25 mm margins, Helvetica 11 pt, Latin-1 only after typographic normalisation.
- No inbound port: the listener only makes outbound HTTPS requests to ntfy.sh.
- Only job ids present in the database are accepted; at most `max_letters_per_day` (default 10) new letters per 24 h.
- `config/profile.yaml`, `data/` (letters, CV cache) are never committed.
- Git: branch `feature/19-cover-letters`, Conventional Commits, one PR closing #19, no attribution trailer or AI mention; commit/PR text must not contain the word "claude" (user hook).
- User-facing strings (notifications, email) in French; code, prompts and docs in English.

## Review Focus

1. **Offer description missing** (rejected/duplicate jobs have an empty description) → the letter is still written from title and company; the fidelity check still runs → `tests/letters/test_service.py::test_letter_for_a_job_without_description` (Task 9).
2. **Double tap** → second request re-delivers the stored PDF without any LLM call → `tests/letters/test_service.py::test_second_request_redelivers_without_llm` (Task 9).
3. **LLM text with typographic characters or emoji** → PDF renders, dropped characters reported → `tests/letters/test_pdf.py::test_render_normalises_typography_and_reports_dropped` (Task 7).
4. **Stream disconnects or a request crashes** → listener keeps running and resumes from the last id → `tests/letters/test_inbox.py::test_listener_survives_errors_and_resumes` (Task 9).
5. **CV download fails** with a stale cache → stale text used; without cache → failure notification → `tests/letters/test_cv.py::test_stale_cache_is_used_when_download_fails` (Task 5).

---

### Task 1: Letter settings in the profile

**Files:**
- Modify: `intern_radar/config.py`, `config/profile.example.yaml`, `tests/test_config.py`

**Interfaces:**
- Produces: `config.Contact(name, location, phone, email, linkedin, github)`; `Profile` gains `requests_topic: str | None = None`, `cv_url: str | None = None`, `letters_email: str | None = None`, `smtp_app_password: str | None = None`, `letter_model: str = "sonnet"`, `max_letters_per_day: int = 10`, `contact: Contact | None = None`.

- [ ] **Step 1: Failing tests** — add `Contact` to the existing `from intern_radar.config import (...)` block at the top of `tests/test_config.py`, then append:

```python
CONTACT = """contact:
  name: Rayân Mouahid
  location: Paris, France
  phone: "+33 7 00 00 00 00"
  email: me@example.com
  linkedin: linkedin.com/in/me
  github: github.com/me
"""


def test_load_profile_reads_letter_settings(tmp_path):
    content = PROFILE + CONTACT + "requests_topic: req-topic\ncv_url: https://cv\n"
    profile = load_profile(write(tmp_path, "profile.yaml", content))
    assert profile.contact == Contact(
        "Rayân Mouahid",
        "Paris, France",
        "+33 7 00 00 00 00",
        "me@example.com",
        "linkedin.com/in/me",
        "github.com/me",
    )
    assert profile.requests_topic == "req-topic"
    assert profile.cv_url == "https://cv"
    assert profile.letter_model == "sonnet"
    assert profile.max_letters_per_day == 10


def test_letter_settings_are_optional(tmp_path):
    profile = load_profile(write(tmp_path, "profile.yaml", PROFILE))
    assert profile.contact is None
    assert profile.requests_topic is None


def test_incomplete_contact_is_rejected(tmp_path):
    content = PROFILE + "contact: {name: X}\n"
    with pytest.raises(ConfigError, match="contact"):
        load_profile(write(tmp_path, "profile.yaml", content))
```

Run: `poetry run pytest tests/test_config.py -q` → FAIL (`cannot import name 'Contact'`).

- [ ] **Step 2: Implement** — in `intern_radar/config.py`, add before `Profile`:

```python
@dataclass(frozen=True)
class Contact:
    name: str
    location: str
    phone: str
    email: str
    linkedin: str
    github: str
```

add to `Profile` after `thresholds`:

```python
    requests_topic: str | None = None
    cv_url: str | None = None
    letters_email: str | None = None
    smtp_app_password: str | None = None
    letter_model: str = "sonnet"
    max_letters_per_day: int = 10
    contact: Contact | None = None
```

and in `load_profile`, before `return Profile(**values)`:

```python
    if "contact" in data:
        values["contact"] = _build(Contact, data["contact"], "contact")
```

- [ ] **Step 3: Example profile** — append to `config/profile.example.yaml`:

```yaml
# --- Cover letters (optional) ---
# requests_topic: intern-radar-requests-CHANGE-ME   # second secret topic
# cv_url: https://docs.google.com/document/d/<id>/export?format=pdf
# letters_email: you@gmail.com
# smtp_app_password: xxxx xxxx xxxx xxxx          # Gmail app password
# letter_model: sonnet
# max_letters_per_day: 10
# contact:
#   name: Your Name
#   location: Paris, France
#   phone: "+33 ..."
#   email: you@gmail.com
#   linkedin: linkedin.com/in/you
#   github: github.com/you
```

- [ ] **Step 4: Verify and commit**

Run: `poetry run pytest -q && poetry run ruff check . && poetry run ruff format --check .` → all pass.

```bash
git add intern_radar/config.py config/profile.example.yaml tests/test_config.py
git commit -m "feat(letters): add cover letter settings to the profile"
```

---

### Task 2: Store support for letters

**Files:**
- Modify: `intern_radar/store.py`, `tests/test_store.py`

**Interfaces:**
- Produces on `Store`: `get_job(job_id: str) -> Job | None`, `save_letter(job_id: str, path: str, report: dict, now: datetime) -> None`, `letter(job_id: str) -> tuple[str, dict] | None`, `letters_since(since: datetime) -> int`, `get_meta(key: str) -> str | None`, `set_meta(key: str, value: str) -> None`.

- [ ] **Step 1: Failing tests** — append to `tests/test_store.py`:

```python
def test_get_job(store):
    store.add(make_job(id="a", description="full"), "pending", NOW)
    assert store.get_job("a") == make_job(id="a", description="full")
    assert store.get_job("missing") is None


def test_letters_are_saved_counted_and_replaced(store):
    store.save_letter("a", "/tmp/a.pdf", {"ai_changes": 2}, NOW)
    store.save_letter("b", "/tmp/b.pdf", {}, NOW - timedelta(days=2))
    assert store.letter("a") == ("/tmp/a.pdf", {"ai_changes": 2})
    assert store.letter("zzz") is None
    assert store.letters_since(NOW - timedelta(days=1)) == 1
    store.save_letter("a", "/tmp/a2.pdf", {}, NOW)
    assert store.letter("a") == ("/tmp/a2.pdf", {})


def test_meta_values(store):
    assert store.get_meta("k") is None
    store.set_meta("k", "v1")
    store.set_meta("k", "v2")
    assert store.get_meta("k") == "v2"
```

Run: `poetry run pytest tests/test_store.py -q` → FAIL (`AttributeError: 'Store' object has no attribute 'get_job'`).

- [ ] **Step 2: Implement** — append to `SCHEMA` in `intern_radar/store.py` (inside the string, after `llm_health`):

```sql
CREATE TABLE IF NOT EXISTS letters (
    job_id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    report TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

and add to `Store` (new section after the jobs section):

```python
    def get_job(self, job_id: str) -> Job | None:
        row = self._db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    # --- letters and meta -------------------------------------------------

    def save_letter(
        self, job_id: str, path: str, report: dict, now: datetime
    ) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO letters (job_id, path, created_at, report)"
                " VALUES (?, ?, ?, ?)",
                (job_id, path, now.isoformat(), json.dumps(report)),
            )

    def letter(self, job_id: str) -> tuple[str, dict] | None:
        row = self._db.execute(
            "SELECT path, report FROM letters WHERE job_id = ?", (job_id,)
        ).fetchone()
        return (row["path"], json.loads(row["report"])) if row else None

    def letters_since(self, since: datetime) -> int:
        row = self._db.execute(
            "SELECT count(*) AS n FROM letters WHERE created_at >= ?",
            (since.isoformat(),),
        ).fetchone()
        return row["n"]

    def get_meta(self, key: str) -> str | None:
        row = self._db.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value)
            )
```

- [ ] **Step 3: Verify and commit**

Run: `poetry run pytest -q && poetry run ruff check . && poetry run ruff format --check .` → all pass.

```bash
git add intern_radar/store.py tests/test_store.py
git commit -m "feat(letters): store generated letters and listener state"
```

---

### Task 3: Letter button on offer notifications

**Files:**
- Modify: `intern_radar/notifier.py`, `intern_radar/pipeline.py`, `tests/test_notifier.py`, `tests/test_pipeline.py`

**Interfaces:**
- Produces: `notifier.Action(label: str, url: str, method: str | None = None, body: str | None = None)`; `Message.actions: tuple[Action, ...]`; `format_immediate(scored: ScoredJob, letter_request_url: str | None = None) -> Message`.

- [ ] **Step 1: Failing tests** — in `tests/test_notifier.py`: import `Action`; in `test_format_immediate_uses_the_card_layout` replace the actions assertion with

```python
    assert message.actions == (Action("Voir l'offre", "https://example.com/jobs/1"),)
```

in `test_ntfy_notifier_posts_json_to_the_server_root` replace the message and expected actions with

```python
    message = Message(
        "T",
        "B",
        4,
        ("fire",),
        "https://u",
        (
            Action("Voir l'offre", "https://u"),
            Action("Lettre", "https://ntfy.sh/req", method="POST", body="job-1"),
        ),
    )
```

```python
        "actions": [
            {"action": "view", "label": "Voir l'offre", "url": "https://u"},
            {
                "action": "http",
                "label": "Lettre",
                "url": "https://ntfy.sh/req",
                "method": "POST",
                "body": "job-1",
            },
        ],
```

and append:

```python
def test_format_immediate_adds_the_letter_button():
    message = format_immediate(scored(), "https://ntfy.sh/req")
    assert message.actions[1] == Action(
        "✍️ Lettre de motivation", "https://ntfy.sh/req", method="POST", body="j1"
    )
```

(`scored()` builds the job with id `"j1"`.)

Append to `tests/test_pipeline.py`:

```python
def test_notifications_carry_the_letter_button_when_configured():
    notifier = FakeNotifier()
    pipeline, _, _ = build(
        {"fake": FakeSource([make_job(id="good", tier="S")])},
        FakeScorer({"good": make_assessment(ai_relevance=9)}),
        notifier,
        requests_topic="req-topic",
    )
    pipeline.run()
    button = notifier.sent[0].actions[1]
    assert (button.url, button.body) == ("https://ntfy.sh/req-topic", "good")
```

Run: `poetry run pytest tests/test_notifier.py tests/test_pipeline.py -q` → FAIL (`cannot import name 'Action'`).

- [ ] **Step 2: Implement** — in `intern_radar/notifier.py` add before `Message`:

```python
@dataclass(frozen=True)
class Action:
    """A notification button: opens `url`, or sends an HTTP request if `method`."""

    label: str
    url: str
    method: str | None = None
    body: str | None = None
```

change `Message.actions` to `actions: tuple[Action, ...] = ()`, replace the actions block of `NtfyNotifier.send` with

```python
        if message.actions:
            payload["actions"] = [_action_payload(a) for a in message.actions]
```

add

```python
def _action_payload(action: Action) -> dict[str, str]:
    if action.method is None:
        return {"action": "view", "label": action.label, "url": action.url}
    return {
        "action": "http",
        "label": action.label,
        "url": action.url,
        "method": action.method,
        "body": action.body or "",
    }
```

and make `format_immediate` take `letter_request_url: str | None = None` and build

```python
    actions = [Action("Voir l'offre", job.url)]
    if letter_request_url:
        actions.append(
            Action(
                "✍️ Lettre de motivation",
                letter_request_url,
                method="POST",
                body=job.id,
            )
        )
```

passing `actions=tuple(actions)` to `Message`.

In `intern_radar/pipeline.py` `_notify`, compute once before the loop

```python
        topic = self._profile.requests_topic
        letter_url = (
            f"{self._profile.ntfy_server.rstrip('/')}/{topic}" if topic else None
        )
```

and call `format_immediate(scored, letter_url)`.

- [ ] **Step 3: Verify and commit**

Run: `poetry run pytest -q && poetry run ruff check . && poetry run ruff format --check .` → all pass.

```bash
git add intern_radar/notifier.py intern_radar/pipeline.py tests/test_notifier.py tests/test_pipeline.py
git commit -m "feat(letters): add a cover letter button to offer notifications"
```

---

### Task 4: Pure letter checks

**Files:**
- Create: `intern_radar/letters/__init__.py` (docstring only), `intern_radar/letters/checks.py`, `tests/letters/__init__.py` (empty), `tests/letters/test_checks.py`

**Interfaces:**
- Produces: `checks.BLACKLIST: tuple[str, ...]`, `keyword_coverage(text: str, keywords: list[str]) -> tuple[list[str], list[str]]` (present, missing), `blacklisted(text: str) -> list[str]`, `unverified_tokens(text: str, sources: list[str]) -> list[str]`.

- [ ] **Step 1: Failing tests** — `tests/letters/test_checks.py`:

```python
from intern_radar.letters.checks import (
    blacklisted,
    keyword_coverage,
    unverified_tokens,
)


def test_keyword_coverage_is_case_insensitive_on_whole_terms():
    text = "I used python, FastAPI and C++ on a RAG pipeline."
    present, missing = keyword_coverage(text, ["Python", "C++", "RAG", "Go", "API"])
    assert present == ["Python", "C++", "RAG"]
    assert missing == ["Go", "API"]


def test_blacklisted_finds_cliches_and_em_dashes():
    text = "I am thrilled to apply — and eager to leverage my skills."
    assert blacklisted(text) == ["thrilled", "leverage", "—"]
    assert blacklisted("I built a RAG agent in Python.") == []


def test_unverified_tokens_flags_unknown_names_and_numbers():
    text = (
        "I built a RAG agent at SYSETELE. My work at Google improved latency "
        "by 40%. During 2027 I am available."
    )
    sources = ["RAG agent SYSETELE internship", "available March 2027"]
    assert unverified_tokens(text, sources) == ["Google", "40%"]


def test_sentence_initial_words_are_not_flagged():
    assert unverified_tokens("During my internship I learned a lot.", [""]) == []
```

Run: `poetry run pytest tests/letters -q` → FAIL (`No module named 'intern_radar.letters'`).

- [ ] **Step 2: Implement** — `intern_radar/letters/__init__.py`:

```python
"""On-demand cover letters for stored internship offers."""
```

`intern_radar/letters/checks.py`:

```python
"""Pure checks applied to generated cover letters."""

import re

# Phrases that make a letter read as generic or machine-written.
BLACKLIST: tuple[str, ...] = (
    "thrilled",
    "passionate about",
    "leverage",
    "leveraging",
    "fast-paced",
    "delve",
    "cutting-edge",
    "in today's",
    "excited to apply",
    "synergy",
    "tapestry",
    "embark",
    "testament to",
    "unwavering",
    "seamless",
    "—",
)
TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)*%?|[A-Za-z][\w+#.-]*[\w+#]|[A-Za-z]")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _contains(text: str, phrase: str) -> bool:
    pattern = rf"(?<!\w){re.escape(phrase)}(?!\w)"
    return re.search(pattern, text, re.IGNORECASE) is not None


def keyword_coverage(text: str, keywords: list[str]) -> tuple[list[str], list[str]]:
    present = [k for k in keywords if _contains(text, k)]
    missing = [k for k in keywords if not _contains(text, k)]
    return present, missing


def blacklisted(text: str) -> list[str]:
    return [
        phrase
        for phrase in BLACKLIST
        if (phrase in text if not phrase[0].isalnum() else _contains(text, phrase))
    ]


def unverified_tokens(text: str, sources: list[str]) -> list[str]:
    """Proper nouns and numbers of `text` found in none of `sources`."""
    haystack = " ".join(sources)
    flagged: list[str] = []
    for sentence in SENTENCE_RE.split(text):
        for index, word in enumerate(TOKEN_RE.findall(sentence)):
            is_number = word[0].isdigit()
            is_proper = len(word) > 1 and word[0].isupper() and (
                index > 0 or any(c.isupper() for c in word[1:])
            )
            if (is_number or is_proper) and word not in flagged:
                if not _contains(haystack, word):
                    flagged.append(word)
    return flagged
```

- [ ] **Step 3: Verify and commit**

Run: `poetry run pytest tests/letters -q` → pass; full suite and ruff pass.

```bash
git add intern_radar/letters tests/letters
git commit -m "feat(letters): add keyword, cliche and fidelity checks"
```

---

### Task 5: CV text source

**Files:**
- Create: `intern_radar/letters/cv.py`, `tests/letters/test_cv.py`
- Modify: `pyproject.toml`, `poetry.lock` (dependencies)

**Interfaces:**
- Produces: `cv.CvError`, `cv.pdf_text(data: bytes) -> str`, `cv.CvSource(client: httpx.Client, url: str, cache_path: Path, max_age: timedelta = timedelta(hours=24), clock: Callable[[], datetime] = …)` with `text() -> str`.

- [ ] **Step 1: Dependencies**

```bash
poetry add fpdf2 pypdf
```

- [ ] **Step 2: Failing tests** — `tests/letters/test_cv.py`:

```python
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fpdf import FPDF

from intern_radar.letters.cv import CvError, CvSource, pdf_text
from tests.factories import mock_client

URL = "https://docs.example/cv/export"
NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)


def make_pdf(text: str) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 5, text)
    return bytes(pdf.output())


def pdf_route(text):
    return lambda request: httpx.Response(200, content=make_pdf(text))


def test_pdf_text_normalises_whitespace():
    assert pdf_text(make_pdf("RAYÂN   MOUAHID\nRAG  agent")) == "RAYÂN MOUAHID\nRAG agent"


def test_downloads_and_caches(tmp_path):
    cache = tmp_path / "cv.json"
    source = CvSource(mock_client({f"GET {URL}": pdf_route("RAG agent")}), URL,
                      cache, clock=lambda: NOW)
    assert source.text() == "RAG agent"
    assert json.loads(cache.read_text())["text"] == "RAG agent"
    offline = CvSource(mock_client({}), URL, cache, clock=lambda: NOW)
    assert offline.text() == "RAG agent"


def test_stale_cache_is_used_when_download_fails(tmp_path):
    cache = tmp_path / "cv.json"
    cache.write_text(json.dumps(
        {"fetched_at": (NOW - timedelta(days=3)).isoformat(), "text": "old CV"}))
    source = CvSource(mock_client({}), URL, cache, clock=lambda: NOW)
    assert source.text() == "old CV"


def test_stale_cache_is_refreshed(tmp_path):
    cache = tmp_path / "cv.json"
    cache.write_text(json.dumps(
        {"fetched_at": (NOW - timedelta(days=3)).isoformat(), "text": "old CV"}))
    source = CvSource(mock_client({f"GET {URL}": pdf_route("new CV")}), URL,
                      cache, clock=lambda: NOW)
    assert source.text() == "new CV"


def test_no_cache_and_no_download_raises(tmp_path):
    source = CvSource(mock_client({}), URL, tmp_path / "cv.json", clock=lambda: NOW)
    with pytest.raises(CvError, match="CV"):
        source.text()
```

Run: `poetry run pytest tests/letters/test_cv.py -q` → FAIL (`No module named 'intern_radar.letters.cv'`).

- [ ] **Step 3: Implement** — `intern_radar/letters/cv.py`:

```python
"""The candidate's CV text, read from its PDF export and cached."""

import io
import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from pypdf import PdfReader
from pypdf.errors import PdfReadError

log = logging.getLogger(__name__)


class CvError(Exception):
    """The CV could not be read."""


def pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\s*\n\s*", "\n", text).strip()


class CvSource:
    def __init__(
        self,
        client: httpx.Client,
        url: str,
        cache_path: Path,
        max_age: timedelta = timedelta(hours=24),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._client = client
        self._url = url
        self._cache_path = cache_path
        self._max_age = max_age
        self._clock = clock

    def text(self) -> str:
        cached = self._read_cache()
        now = self._clock()
        if cached and now - cached[0] < self._max_age:
            return cached[1]
        try:
            response = self._client.get(self._url)
            response.raise_for_status()
            text = pdf_text(response.content)
        except (httpx.HTTPError, PdfReadError, ValueError) as exc:
            if cached:
                log.warning("CV download failed, using cached copy: %s", exc)
                return cached[1]
            raise CvError(f"CV unavailable: {type(exc).__name__}") from exc
        if not text:
            raise CvError("CV PDF contains no text")
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(
            json.dumps({"fetched_at": now.isoformat(), "text": text}),
            encoding="utf-8",
        )
        return text

    def _read_cache(self) -> tuple[datetime, str] | None:
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            return datetime.fromisoformat(data["fetched_at"]), data["text"]
        except (OSError, ValueError, KeyError):
            return None
```

- [ ] **Step 4: Verify and commit**

Run: `poetry run pytest -q && poetry run ruff check . && poetry run ruff format --check .` → pass.

```bash
git add pyproject.toml poetry.lock intern_radar/letters/cv.py tests/letters/test_cv.py
git commit -m "feat(letters): read the CV from its PDF export with a daily cache"
```

---

### Task 6: Letter writer (LLM steps)

**Files:**
- Create: `intern_radar/letters/writer.py`, `tests/letters/test_writer.py`

**Interfaces:**
- Consumes: `scorer.LLMBackend`, `scorer.LLMError`, `checks.*`, `models.Job`
- Produces: `writer.Letter(language: str, greeting: str, paragraphs: tuple[str, ...], closing: str)` with `body() -> str`, `text() -> str`; `writer.LetterReport(keywords_present, keywords_missing, keywords_not_in_cv, ai_changes: int, blacklist_left, unverified)` (tuples of str except `ai_changes`); `writer.LetterWriter(backend, cv_text: str, window_start: date, window_end: date, min_months: int)` with `write(job: Job) -> tuple[Letter, LetterReport]`; schemas `LETTER_SCHEMA`, `KEYWORDS_SCHEMA`, `REWRITE_SCHEMA`.

- [ ] **Step 1: Failing tests** — `tests/letters/test_writer.py`:

```python
from datetime import date

import pytest

from intern_radar.letters.writer import (
    KEYWORDS_SCHEMA,
    LETTER_SCHEMA,
    REWRITE_SCHEMA,
    LetterWriter,
)
from intern_radar.scorer import LLMError
from tests.factories import make_job

CV = "RAG agent in Python with PyTorch. Internship at SYSETELE."
CLEAN = [
    "Your team builds retrieval systems for machine learning products.",
    "At SYSETELE I built a RAG agent in Python and PyTorch.",
    "I am available from March to August 2027.",
]


class ScriptedBackend:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def complete(self, prompt, schema):
        self.calls.append((prompt, schema))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def draft(paragraphs):
    return {"language": "en", "greeting": "Dear Hiring Team,",
            "paragraphs": paragraphs, "closing": "Sincerely,"}


def keywords(*pairs):
    return {"keywords": [{"keyword": k, "in_cv": v} for k, v in pairs]}


def rewrite(paragraphs, changes):
    return {"paragraphs": paragraphs, "changes": changes}


def make_writer(backend):
    return LetterWriter(backend, CV, date(2027, 3, 8), date(2027, 8, 31), 4)


def test_full_flow_revises_missing_keywords_and_humanizes():
    without_pytorch = [CLEAN[0], "At SYSETELE I built a RAG agent in Python.", CLEAN[2]]
    backend = ScriptedBackend(
        draft(without_pytorch),
        keywords(("Python", True), ("PyTorch", True), ("Kubernetes", False)),
        rewrite(CLEAN, 1),
        rewrite(CLEAN, 3),
    )
    letter, report = make_writer(backend).write(make_job(company="Acme"))
    assert [schema for _, schema in backend.calls] == [
        LETTER_SCHEMA, KEYWORDS_SCHEMA, REWRITE_SCHEMA, REWRITE_SCHEMA]
    assert "PyTorch" in backend.calls[2][0]
    assert letter.paragraphs == tuple(CLEAN)
    assert report.keywords_present == ("Python", "PyTorch")
    assert report.keywords_missing == ()
    assert report.keywords_not_in_cv == ("Kubernetes",)
    assert report.ai_changes == 3
    assert report.blacklist_left == ()


def test_no_revision_when_every_cv_keyword_is_present():
    backend = ScriptedBackend(
        draft(CLEAN), keywords(("Python", True)), rewrite(CLEAN, 0))
    make_writer(backend).write(make_job())
    assert len(backend.calls) == 3


def test_blacklisted_phrases_trigger_one_more_rewrite():
    cliche = [CLEAN[0], "I am thrilled to build RAG agents in Python.", CLEAN[2]]
    backend = ScriptedBackend(
        draft(CLEAN), keywords(), rewrite(cliche, 2), rewrite(CLEAN, 1))
    letter, report = make_writer(backend).write(make_job())
    assert "thrilled" in backend.calls[3][0]
    assert report.ai_changes == 3
    assert report.blacklist_left == ()


def test_draft_prompt_carries_the_cv_and_the_rules():
    backend = ScriptedBackend(draft(CLEAN), keywords(), rewrite(CLEAN, 0))
    make_writer(backend).write(make_job(title="ML Intern", description="LLM work"))
    prompt = backend.calls[0][0]
    assert CV in prompt and "ML Intern" in prompt and "LLM work" in prompt
    assert "Never invent" in prompt


def test_report_flags_unverified_facts():
    invented = [CLEAN[0], "At Google I cut latency by 40%.", CLEAN[2]]
    backend = ScriptedBackend(draft(CLEAN), keywords(), rewrite(invented, 1))
    _, report = make_writer(backend).write(make_job(company="Acme"))
    assert report.unverified == ("Google", "40%")


@pytest.mark.parametrize(
    "answer",
    [draft(CLEAN[:2]), draft(["", "b", "c"]), {"paragraphs": "x"}],
)
def test_invalid_letters_raise_llm_error(answer):
    with pytest.raises(LLMError):
        make_writer(ScriptedBackend(answer)).write(make_job())
```

Run: `poetry run pytest tests/letters/test_writer.py -q` → FAIL (`No module named 'intern_radar.letters.writer'`).

- [ ] **Step 2: Implement** — `intern_radar/letters/writer.py`:

```python
"""Write a cover letter with the LLM: draft, ATS revision, anti-AI rewrite."""

from dataclasses import dataclass
from datetime import date
from typing import Any

from intern_radar.letters.checks import (
    blacklisted,
    keyword_coverage,
    unverified_tokens,
)
from intern_radar.models import Job
from intern_radar.scorer import LLMBackend, LLMError

DESCRIPTION_LIMIT = 6000
PARAGRAPHS = {"type": "array", "items": {"type": "string"}, "minItems": 3,
              "maxItems": 3}
LETTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "language": {"type": "string"},
        "greeting": {"type": "string"},
        "paragraphs": PARAGRAPHS,
        "closing": {"type": "string"},
    },
    "required": ["language", "greeting", "paragraphs", "closing"],
}
KEYWORDS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "keywords": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string"},
                    "in_cv": {"type": "boolean"},
                },
                "required": ["keyword", "in_cv"],
            },
        }
    },
    "required": ["keywords"],
}
REWRITE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "paragraphs": PARAGRAPHS,
        "changes": {"type": "integer", "minimum": 0},
    },
    "required": ["paragraphs", "changes"],
}

DRAFT = """You write the body of a cover letter for an internship application.

Candidate CV (the ONLY source of facts about the candidate):
<cv>
{cv}
</cv>

Internship offer:
Company: {company}
Title: {title}
Location: {location}
Description:
{description}

{window}

Rules:
- Language: English, unless the offer is written in Spanish or French; then
  use that language.
- About 300 words in exactly 3 paragraphs.
- Paragraph 1: why this company and this role, citing one concrete element
  of the offer.
- Paragraph 2: two or three projects or experiences from the CV, each tied
  explicitly to a mission or requirement of the offer.
- Paragraph 3: the availability above and one short, sober closing sentence.
- Never invent a skill, tool, number, employer, school or experience that
  is not in the CV.
- No filler, no cliches, no em dashes.
Return the greeting (e.g. "Dear Hiring Team,"), the 3 paragraphs, the
closing (e.g. "Sincerely,") and the language as an ISO code."""

KEYWORDS = """List the 10 to 15 most important keywords (skills, tools,
technologies, concepts) an applicant tracking system would look for in this
internship offer. Set in_cv to true only when the CV below shows that the
candidate has it.

<cv>
{cv}
</cv>

Offer: {title} at {company}
{description}"""

REVISE = """Revise this cover letter so that it naturally mentions these
keywords, which the CV supports: {keywords}. Keep the facts, the language,
the 3-paragraph structure and the length. Add nothing the CV does not
support.

<cv>
{cv}
</cv>

Letter:
{body}

Return the 3 paragraphs and the number of passages you changed."""

HUMANIZE = """Read this cover letter as a sceptical recruiter who has seen
thousands of AI-generated letters. Rewrite every generic or AI-sounding
passage into plain, concrete sentences: cliches (such as "thrilled",
"passionate about", "leverage", "fast-paced", "cutting-edge", "delve"),
em dashes, symmetrical lists of three, claims without an example. Keep the
facts, the language, the 3-paragraph structure and the length. Do not add
facts.{extra}

Letter:
{body}

Return the 3 paragraphs and the number of passages you changed."""


@dataclass(frozen=True)
class Letter:
    language: str
    greeting: str
    paragraphs: tuple[str, ...]
    closing: str

    def body(self) -> str:
        return "\n\n".join(self.paragraphs)

    def text(self) -> str:
        return f"{self.greeting}\n\n{self.body()}\n\n{self.closing}"


@dataclass(frozen=True)
class LetterReport:
    keywords_present: tuple[str, ...]
    keywords_missing: tuple[str, ...]
    keywords_not_in_cv: tuple[str, ...]
    ai_changes: int
    blacklist_left: tuple[str, ...]
    unverified: tuple[str, ...]


def _paragraphs(result: dict[str, Any]) -> tuple[str, ...]:
    paragraphs = result.get("paragraphs")
    if (
        not isinstance(paragraphs, list)
        or len(paragraphs) != 3
        or not all(isinstance(p, str) and p.strip() for p in paragraphs)
    ):
        raise LLMError("LLM returned an invalid letter")
    return tuple(p.strip() for p in paragraphs)


class LetterWriter:
    def __init__(
        self,
        backend: LLMBackend,
        cv_text: str,
        window_start: date,
        window_end: date,
        min_months: int,
    ) -> None:
        self._backend = backend
        self._cv = cv_text
        self._window = (
            f"The candidate is available for an internship of at least "
            f"{min_months} months between {window_start:%B} {window_start.year} "
            f"and {window_end:%B} {window_end.year}."
        )

    def write(self, job: Job) -> tuple[Letter, LetterReport]:
        letter = self._draft(job)
        pairs = self._keywords(job)
        in_cv = [keyword for keyword, ok in pairs if ok]
        not_in_cv = tuple(keyword for keyword, ok in pairs if not ok)
        _, missing = keyword_coverage(letter.body(), in_cv)
        if missing:
            prompt = REVISE.format(
                keywords=", ".join(missing), cv=self._cv, body=letter.body()
            )
            letter, _ = self._rewrite(letter, prompt)
        letter, changes = self._rewrite(
            letter, HUMANIZE.format(extra="", body=letter.body())
        )
        left = blacklisted(letter.body())
        if left:
            extra = f" These phrases must disappear: {', '.join(left)}."
            letter, more = self._rewrite(
                letter, HUMANIZE.format(extra=extra, body=letter.body())
            )
            changes += more
            left = blacklisted(letter.body())
        present, missing = keyword_coverage(letter.body(), in_cv)
        sources = [
            self._cv,
            job.company,
            job.title,
            job.location,
            job.description,
            self._window,
        ]
        report = LetterReport(
            keywords_present=tuple(present),
            keywords_missing=tuple(missing),
            keywords_not_in_cv=not_in_cv,
            ai_changes=changes,
            blacklist_left=tuple(left),
            unverified=tuple(unverified_tokens(letter.body(), sources)),
        )
        return letter, report

    def _draft(self, job: Job) -> Letter:
        result = self._backend.complete(
            DRAFT.format(
                cv=self._cv,
                company=job.company,
                title=job.title,
                location=job.location or "not stated",
                description=job.description[:DESCRIPTION_LIMIT] or "not provided",
                window=self._window,
            ),
            LETTER_SCHEMA,
        )
        paragraphs = _paragraphs(result)
        return Letter(
            language=str(result.get("language") or "en"),
            greeting=str(result.get("greeting") or "Dear Hiring Team,"),
            paragraphs=paragraphs,
            closing=str(result.get("closing") or "Sincerely,"),
        )

    def _keywords(self, job: Job) -> list[tuple[str, bool]]:
        result = self._backend.complete(
            KEYWORDS.format(
                cv=self._cv,
                title=job.title,
                company=job.company,
                description=job.description[:DESCRIPTION_LIMIT],
            ),
            KEYWORDS_SCHEMA,
        )
        pairs = []
        for item in result.get("keywords") or []:
            if isinstance(item, dict) and isinstance(item.get("keyword"), str):
                pairs.append((item["keyword"].strip(), item.get("in_cv") is True))
        return [(keyword, ok) for keyword, ok in pairs if keyword]

    def _rewrite(self, letter: Letter, prompt: str) -> tuple[Letter, int]:
        result = self._backend.complete(prompt, REWRITE_SCHEMA)
        changes = result.get("changes")
        count = changes if isinstance(changes, int) and changes >= 0 else 0
        return (
            Letter(letter.language, letter.greeting, _paragraphs(result),
                   letter.closing),
            count,
        )
```

- [ ] **Step 3: Verify and commit**

Run: `poetry run pytest -q && poetry run ruff check . && poetry run ruff format --check .` → pass (let `ruff format` reflow the long literals).

```bash
git add intern_radar/letters/writer.py tests/letters/test_writer.py
git commit -m "feat(letters): write letters with ATS revision and anti-cliche rewrite"
```

---

### Task 7: PDF rendering

**Files:**
- Create: `intern_radar/letters/pdf.py`, `tests/letters/test_pdf.py`

**Interfaces:**
- Consumes: `writer.Letter`, `config.Contact`, `models.Job`
- Produces: `pdf.to_latin1(text: str) -> tuple[str, list[str]]`, `pdf.file_name(last_name: str, company: str, title: str) -> str`, `pdf.render(letter: Letter, job: Job, contact: Contact, today: date) -> tuple[bytes, list[str]]` (PDF bytes, dropped characters).

- [ ] **Step 1: Failing tests** — `tests/letters/test_pdf.py`:

```python
import io
from datetime import date

from pypdf import PdfReader

from intern_radar.config import Contact
from intern_radar.letters.pdf import file_name, render, to_latin1
from intern_radar.letters.writer import Letter
from tests.factories import make_job

CONTACT = Contact("Rayân Mouahid", "Paris, France", "+33 7 00", "me@example.com",
                  "linkedin.com/in/me", "github.com/me")
LETTER = Letter("en", "Dear Hiring Team,",
                ("First paragraph.", "Second paragraph.", "Third paragraph."),
                "Sincerely,")


def text_of(data: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)


def test_to_latin1():
    assert to_latin1("It’s “good” — really…") == ('It\'s "good" - really...', [])
    assert to_latin1("Rayân café 🚀") == ("Rayân café ", ["🚀"])


def test_file_name():
    assert file_name("Mouahid", "Hugging Face", "ML Intern (2027)") == (
        "Mouahid_CoverLetter_Hugging-Face_ML-Intern-2027.pdf"
    )
    long_name = file_name("Mouahid", "Amazon", "Robotics " * 30)
    assert len(long_name) <= 80 and long_name.endswith(".pdf")


def test_render_contains_header_body_and_signature():
    job = make_job(company="Acme", title="ML Intern", location="London, UK")
    data, dropped = render(LETTER, job, CONTACT, date(2026, 9, 24))
    text = text_of(data)
    assert data.startswith(b"%PDF")
    assert dropped == []
    for expected in ("Rayân Mouahid", "me@example.com", "September 24, 2026",
                     "Acme - Hiring Team", "Re: ML Intern (London, UK)",
                     "Second paragraph.", "Sincerely,"):
        assert expected in text


def test_render_normalises_typography_and_reports_dropped():
    letter = Letter("en", "Dear Team,", ("It’s great — 🚀", "b", "c"), "Best,")
    data, dropped = render(letter, make_job(), CONTACT, date(2026, 9, 24))
    assert "It's great -" in text_of(data)
    assert dropped == ["🚀"]
```

Run: `poetry run pytest tests/letters/test_pdf.py -q` → FAIL (`No module named 'intern_radar.letters.pdf'`).

- [ ] **Step 2: Implement** — `intern_radar/letters/pdf.py`:

```python
"""Render a cover letter as a simple one-page PDF."""

import re
import unicodedata
from datetime import date

from fpdf import FPDF

from intern_radar.config import Contact
from intern_radar.letters.writer import Letter
from intern_radar.models import Job

TYPOGRAPHY = str.maketrans(
    {
        "’": "'",
        "‘": "'",
        "“": '"',
        "”": '"',
        "—": "-",
        "–": "-",
        "…": "...",
        " ": " ",
        " ": " ",
        "•": "-",
    }
)
LINE_HEIGHT = 5.5
MARGIN = 25


def to_latin1(text: str) -> tuple[str, list[str]]:
    """Latin-1 text for the core PDF font, and the characters dropped."""
    text = text.translate(TYPOGRAPHY)
    dropped = sorted({c for c in text if ord(c) > 255})
    return "".join(c for c in text if ord(c) <= 255), dropped


def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore")
    return re.sub(r"[^A-Za-z0-9]+", "-", ascii_text.decode()).strip("-")


def file_name(last_name: str, company: str, title: str) -> str:
    base = f"{_slug(last_name)}_CoverLetter_{_slug(company)}_{_slug(title)}"
    return base[:76].rstrip("-_") + ".pdf"


def render(
    letter: Letter, job: Job, contact: Contact, today: date
) -> tuple[bytes, list[str]]:
    pdf = FPDF(format="A4")
    pdf.set_margins(MARGIN, MARGIN, MARGIN)
    pdf.set_auto_page_break(True, MARGIN)
    pdf.add_page()
    dropped: set[str] = set()

    def write(text: str, style: str = "", gap: float = 0) -> None:
        clean, lost = to_latin1(text)
        dropped.update(lost)
        pdf.set_font("Helvetica", style=style, size=11)
        pdf.multi_cell(0, LINE_HEIGHT, clean, new_x="LMARGIN", new_y="NEXT")
        if gap:
            pdf.ln(gap)

    write(contact.name, "B")
    write(f"{contact.location} · {contact.phone} · {contact.email}")
    write(f"{contact.linkedin} · {contact.github}", gap=8)
    write(f"{today:%B} {today.day}, {today.year}", gap=6)
    write(f"{job.company} — Hiring Team")
    location = f" ({job.location})" if job.location else ""
    write(f"Re: {job.title}{location}", "B", gap=6)
    write(letter.greeting, gap=3)
    for paragraph in letter.paragraphs:
        write(paragraph, gap=3)
    pdf.ln(2)
    write(letter.closing)
    write(contact.name)
    return bytes(pdf.output()), sorted(dropped)
```

- [ ] **Step 3: Verify and commit**

Run: `poetry run pytest -q && poetry run ruff check . && poetry run ruff format --check .` → pass.

```bash
git add intern_radar/letters/pdf.py tests/letters/test_pdf.py
git commit -m "feat(letters): render cover letters as simple PDFs"
```

---

### Task 8: Delivery (ntfy attachment and Gmail)

**Files:**
- Create: `intern_radar/letters/delivery.py`, `tests/letters/test_delivery.py`

**Interfaces:**
- Produces: `delivery.DeliveryError`; `delivery.NtfyAttachmentSender(server: str, topic: str, client: httpx.Client)` with `send(pdf: bytes, filename: str, title: str, message: str) -> None`; `delivery.GmailSender(address: str, app_password: str, smtp_factory=smtplib.SMTP_SSL)` with `send(subject: str, body: str, pdf: bytes, filename: str) -> None`.

- [ ] **Step 1: Failing tests** — `tests/letters/test_delivery.py`:

```python
import smtplib

import httpx
import pytest

from intern_radar.letters.delivery import (
    DeliveryError,
    GmailSender,
    NtfyAttachmentSender,
)
from tests.factories import mock_client


def test_ntfy_attachment_is_put_with_query_metadata():
    seen = {}

    def handler(request: httpx.Request):
        seen["method"] = request.method
        seen["params"] = dict(request.url.params)
        seen["body"] = request.content
        return httpx.Response(200, json={})

    client = mock_client({"PUT https://ntfy.sh/topic-1": handler})
    NtfyAttachmentSender("https://ntfy.sh/", "topic-1", client).send(
        b"%PDF-1.4", "letter.pdf", "✍️ Lettre prête · Acme", "ATS : 3/4")
    assert seen == {
        "method": "PUT",
        "params": {"filename": "letter.pdf", "title": "✍️ Lettre prête · Acme",
                   "message": "ATS : 3/4", "tags": "memo"},
        "body": b"%PDF-1.4",
    }


def test_ntfy_attachment_failure_raises():
    client = mock_client({"PUT https://ntfy.sh/t": 500})
    with pytest.raises(DeliveryError):
        NtfyAttachmentSender("https://ntfy.sh", "t", client).send(b"x", "a", "b", "c")


class FakeSMTP:
    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout):
        self.address = (host, port)
        self.sent = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        if password == "bad":
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")
        self.credentials = (user, password)

    def send_message(self, message):
        self.sent.append(message)


def test_gmail_sender_attaches_the_pdf():
    FakeSMTP.instances.clear()
    GmailSender("me@gmail.com", "app-pass", FakeSMTP).send(
        "Lettre — Acme", "Corps", b"%PDF", "letter.pdf")
    smtp = FakeSMTP.instances[0]
    assert smtp.address == ("smtp.gmail.com", 465)
    assert smtp.credentials == ("me@gmail.com", "app-pass")
    message = smtp.sent[0]
    assert (message["From"], message["To"]) == ("me@gmail.com", "me@gmail.com")
    assert message["Subject"] == "Lettre — Acme"
    [attachment] = list(message.iter_attachments())
    assert attachment.get_filename() == "letter.pdf"
    assert attachment.get_content() == b"%PDF"


def test_gmail_failure_raises_delivery_error():
    with pytest.raises(DeliveryError, match="e-mail"):
        GmailSender("me@gmail.com", "bad", FakeSMTP).send("s", "b", b"x", "f.pdf")
```

Run: `poetry run pytest tests/letters/test_delivery.py -q` → FAIL (`No module named 'intern_radar.letters.delivery'`).

- [ ] **Step 2: Implement** — `intern_radar/letters/delivery.py`:

```python
"""Deliver a letter PDF through an ntfy attachment and Gmail."""

import smtplib
from collections.abc import Callable
from email.message import EmailMessage

import httpx

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


class DeliveryError(Exception):
    """A letter could not be delivered."""


class NtfyAttachmentSender:
    def __init__(self, server: str, topic: str, client: httpx.Client) -> None:
        self._url = f"{server.rstrip('/')}/{topic}"
        self._client = client

    def send(self, pdf: bytes, filename: str, title: str, message: str) -> None:
        # Metadata goes in the query string: HTTP headers cannot carry UTF-8.
        params = {"filename": filename, "title": title, "message": message,
                  "tags": "memo"}
        try:
            response = self._client.put(self._url, content=pdf, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DeliveryError(f"ntfy: {type(exc).__name__}") from exc


class GmailSender:
    def __init__(
        self,
        address: str,
        app_password: str,
        smtp_factory: Callable[..., smtplib.SMTP_SSL] = smtplib.SMTP_SSL,
    ) -> None:
        self._address = address
        self._password = app_password
        self._smtp_factory = smtp_factory

    def send(self, subject: str, body: str, pdf: bytes, filename: str) -> None:
        message = EmailMessage()
        message["From"] = self._address
        message["To"] = self._address
        message["Subject"] = subject
        message.set_content(body)
        message.add_attachment(
            pdf, maintype="application", subtype="pdf", filename=filename
        )
        try:
            with self._smtp_factory(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
                smtp.login(self._address, self._password)
                smtp.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            raise DeliveryError(f"e-mail: {type(exc).__name__}") from exc
```

- [ ] **Step 3: Verify and commit**

Run: `poetry run pytest -q && poetry run ruff check . && poetry run ruff format --check .` → pass.

```bash
git add intern_radar/letters/delivery.py tests/letters/test_delivery.py
git commit -m "feat(letters): deliver letters as ntfy attachments and by e-mail"
```

---

### Task 9: Letter service and request listener

**Files:**
- Create: `intern_radar/letters/service.py`, `intern_radar/letters/inbox.py`, `tests/letters/test_service.py`, `tests/letters/test_inbox.py`

**Interfaces:**
- Consumes: Tasks 2, 5–8; `notifier.Message`, `notifier.Notifier`
- Produces:
  - `service.LetterService(store, make_writer: Callable[[], LetterWriter], contact: Contact, out_dir: Path, attachments: NtfyAttachmentSender, mail: GmailSender | None, notifier: Notifier, max_per_day: int, clock=…)` with `handle(job_id: str) -> Path | None`
  - `service.format_letter_card(job: Job, report: dict, filename: str, email_status: str) -> str`
  - `inbox.parse_line(line: str) -> tuple[str, str] | None`, `inbox.RequestStream(client, server, topic)` with `messages(since: str | None) -> Iterator[tuple[str, str]]`, `inbox.run_listener(stream, handle, store, sleep=time.sleep, keep_going=lambda: True) -> None`, `inbox.LAST_ID_KEY = "last_request_id"`

- [ ] **Step 1: Failing tests** — `tests/letters/test_service.py`:

```python
from datetime import UTC, datetime, timedelta

from intern_radar.config import Contact
from intern_radar.letters.cv import CvError
from intern_radar.letters.delivery import DeliveryError
from intern_radar.letters.service import LetterService, format_letter_card
from intern_radar.letters.writer import Letter, LetterReport
from intern_radar.store import Store
from tests.factories import make_job

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)
CONTACT = Contact("Rayân Mouahid", "Paris", "+33", "me@example.com", "li", "gh")
LETTER = Letter("en", "Dear Hiring Team,", ("One.", "Two.", "Three."), "Sincerely,")
REPORT = LetterReport(("Python",), ("PyTorch",), ("Kubernetes",), 4, (), ("40%",))


class FakeWriter:
    calls = 0

    def __init__(self, error=None):
        self.error = error

    def write(self, job):
        FakeWriter.calls += 1
        if self.error:
            raise self.error
        return LETTER, REPORT


class Recorder:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send(self, *args, **kwargs):
        if self.fail:
            raise DeliveryError("e-mail: SMTPAuthenticationError")
        self.sent.append(args or kwargs)


def build(tmp_path, writer=None, mail=None, max_per_day=10, jobs=None):
    store = Store(":memory:")
    for job in jobs or [make_job(id="j1", company="Acme", title="ML Intern")]:
        store.add(job, "pending", NOW)
    FakeWriter.calls = 0
    attachments, notifier = Recorder(), Recorder()
    service = LetterService(store, lambda: writer or FakeWriter(), CONTACT,
                            tmp_path / "letters", attachments, mail, notifier,
                            max_per_day, clock=lambda: NOW)
    return service, store, attachments, notifier


def test_generates_stores_and_delivers(tmp_path):
    mail = Recorder()
    service, store, attachments, notifier = build(tmp_path, mail=mail)
    path = service.handle("j1\n")
    assert path.name == "Mouahid_CoverLetter_Acme_ML-Intern.pdf"
    assert path.read_bytes().startswith(b"%PDF")
    stored_path, report = store.letter("j1")
    assert stored_path == str(path) and report["ai_changes"] == 4
    pdf, filename, title, card = attachments.sent[0]
    assert (filename, title) == (path.name, "✍️ Lettre prête · Acme")
    assert "🎯  ATS : 1/2 mots-clés" in card
    assert "📧  Envoyée par e-mail" in card
    assert mail.sent[0]["subject"] == "Lettre — Acme · ML Intern"
    assert notifier.sent == []


def test_second_request_redelivers_without_llm(tmp_path):
    service, _, attachments, _ = build(tmp_path)
    first = service.handle("j1")
    second = service.handle("j1")
    assert first == second and FakeWriter.calls == 1
    assert len(attachments.sent) == 2


def test_unknown_job_is_ignored(tmp_path):
    service, _, attachments, notifier = build(tmp_path)
    assert service.handle("nope") is None
    assert attachments.sent == [] and notifier.sent == []


def test_daily_cap_sends_one_notice(tmp_path):
    jobs = [make_job(id=f"j{i}") for i in range(3)]
    service, store, _, notifier = build(tmp_path, max_per_day=1, jobs=jobs)
    service.handle("j0")
    assert service.handle("j1") is None
    assert service.handle("j2") is None
    assert [m.title for m in notifier.sent] == ["Limite de lettres atteinte"]


def test_writer_failure_sends_a_failure_notification(tmp_path):
    service, store, attachments, notifier = build(
        tmp_path, writer=FakeWriter(CvError("CV unavailable: ConnectError")))
    assert service.handle("j1") is None
    assert notifier.sent[0].title == "❌ Lettre non générée · Acme"
    assert "CV unavailable" in notifier.sent[0].body
    assert store.letter("j1") is None


def test_email_failure_is_reported_in_the_card(tmp_path):
    service, _, attachments, _ = build(tmp_path, mail=Recorder(fail=True))
    service.handle("j1")
    assert "📧  E-mail en échec : e-mail: SMTPAuthenticationError" in (
        attachments.sent[0][3])


def test_letter_for_a_job_without_description(tmp_path):
    job = make_job(id="j1", company="Acme", title="ML Intern", description="")
    service, _, attachments, _ = build(tmp_path, jobs=[job])
    assert service.handle("j1") is not None


def test_format_letter_card_lists_every_check():
    report = {"keywords_present": ["Python"], "keywords_missing": ["Go"],
              "keywords_not_in_cv": ["Rust"], "ai_changes": 2,
              "unverified": ["40%"], "blacklist_left": [], "dropped": []}
    card = format_letter_card(make_job(title="ML Intern"), report, "f.pdf",
                              "📧  Envoyée par e-mail")
    assert card == (
        "ML Intern\n━━━━━━━━━━━━━━━━\n🎯  ATS : 1/2 mots-clés\n"
        "🚫  Absents de ton CV : Rust\n🧹  Anti-IA : 2 tournures corrigées\n"
        "⚠️  À vérifier : 40%\n📧  Envoyée par e-mail\n━━━━━━━━━━━━━━━━\n📎 f.pdf"
    )
```

`tests/letters/test_inbox.py`:

```python
import httpx

from intern_radar.letters.inbox import (
    LAST_ID_KEY,
    RequestStream,
    parse_line,
    run_listener,
)
from intern_radar.store import Store
from tests.factories import mock_client


def test_parse_line_keeps_only_messages():
    assert parse_line('{"id":"a1","event":"message","message":" job-1 "}') == (
        "a1", "job-1")
    assert parse_line('{"id":"k","event":"keepalive"}') is None
    assert parse_line("not json") is None
    assert parse_line("") is None


def test_request_stream_reads_lines_since_the_last_id():
    seen = {}

    def handler(request):
        seen["since"] = request.url.params["since"]
        return httpx.Response(200, content=(
            b'{"id":"o","event":"open"}\n'
            b'{"id":"m1","event":"message","message":"job-1"}\n'))

    client = mock_client({"GET https://ntfy.sh/req/json": handler})
    stream = RequestStream(client, "https://ntfy.sh", "req")
    assert list(stream.messages("m0")) == [("m1", "job-1")]
    assert seen["since"] == "m0"
    list(stream.messages(None))
    assert seen["since"] == "12h"


class FlakyStream:
    def __init__(self):
        self.calls = []

    def messages(self, since):
        self.calls.append(since)
        if len(self.calls) == 1:
            yield ("m1", "boom")
            yield ("m2", "job-2")
            raise httpx.ReadTimeout("dropped")
        yield ("m3", "job-3")


def test_listener_survives_errors_and_resumes():
    store = Store(":memory:")
    handled, sleeps = [], []

    def handle(body):
        if body == "boom":
            raise RuntimeError("bad request")
        handled.append(body)

    stream = FlakyStream()
    rounds = iter([True, True, False])
    run_listener(stream, handle, store, sleep=sleeps.append,
                 keep_going=lambda: next(rounds))
    assert handled == ["job-2", "job-3"]
    assert stream.calls == [None, "m2"]
    assert store.get_meta(LAST_ID_KEY) == "m3"
    assert sleeps[0] == 5
```

Run: `poetry run pytest tests/letters -q` → FAIL (`No module named 'intern_radar.letters.service'` / `...inbox`).

- [ ] **Step 2: Implement** — `intern_radar/letters/service.py`:

```python
"""Handle one cover letter request end to end."""

import logging
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from intern_radar.config import Contact
from intern_radar.letters.cv import CvError
from intern_radar.letters.delivery import (
    DeliveryError,
    GmailSender,
    NtfyAttachmentSender,
)
from intern_radar.letters.pdf import file_name, render
from intern_radar.letters.writer import LetterWriter
from intern_radar.models import Job
from intern_radar.notifier import Message, Notifier
from intern_radar.scorer import LLMError
from intern_radar.store import Store

log = logging.getLogger(__name__)

SEPARATOR = "━" * 16
CAP_NOTICE_KEY = "letters_cap_notice_day"


def format_letter_card(
    job: Job, report: dict[str, Any], filename: str, email_status: str
) -> str:
    present = report.get("keywords_present", [])
    missing = report.get("keywords_missing", [])
    lines = [
        job.title,
        SEPARATOR,
        f"🎯  ATS : {len(present)}/{len(present) + len(missing)} mots-clés",
    ]
    not_in_cv = report.get("keywords_not_in_cv", [])
    if not_in_cv:
        lines.append(f"🚫  Absents de ton CV : {', '.join(not_in_cv)}")
    lines.append(f"🧹  Anti-IA : {report.get('ai_changes', 0)} tournures corrigées")
    flags = [*report.get("unverified", []), *report.get("blacklist_left", [])]
    if flags:
        lines.append(f"⚠️  À vérifier : {', '.join(flags)}")
    lines += [email_status, SEPARATOR, f"📎 {filename}"]
    return "\n".join(lines)


class LetterService:
    def __init__(
        self,
        store: Store,
        make_writer: Callable[[], LetterWriter],
        contact: Contact,
        out_dir: Path,
        attachments: NtfyAttachmentSender,
        mail: GmailSender | None,
        notifier: Notifier,
        max_per_day: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._make_writer = make_writer
        self._contact = contact
        self._out_dir = out_dir
        self._attachments = attachments
        self._mail = mail
        self._notifier = notifier
        self._max_per_day = max_per_day
        self._clock = clock

    def handle(self, job_id: str) -> Path | None:
        job_id = job_id.strip()
        job = self._store.get_job(job_id)
        if job is None:
            log.warning("letter request for unknown job %r", job_id[:80])
            return None
        stored = self._store.letter(job_id)
        if stored and Path(stored[0]).exists():
            path = Path(stored[0])
            self._deliver(job, path, stored[1])
            return path
        now = self._clock()
        if self._store.letters_since(now - timedelta(days=1)) >= self._max_per_day:
            self._cap_notice(now)
            return None
        try:
            letter, report = self._make_writer().write(job)
        except (LLMError, CvError) as exc:
            log.warning("letter for %s failed: %s", job_id, exc)
            self._notifier.send(
                Message(
                    title=f"❌ Lettre non générée · {job.company}",
                    body=f"{job.title}\n{str(exc)[:300]}",
                    priority=3,
                    tags=("x",),
                )
            )
            return None
        pdf, dropped = render(letter, job, self._contact, now.date())
        last_name = self._contact.name.split()[-1]
        path = self._out_dir / file_name(last_name, job.company, job.title)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pdf)
        data = {**asdict(report), "dropped": dropped, "text": letter.text()}
        self._store.save_letter(job_id, str(path), data, now)
        self._deliver(job, path, data)
        return path

    def _deliver(self, job: Job, path: Path, report: dict[str, Any]) -> None:
        pdf = path.read_bytes()
        email_status = "📧  E-mail non configuré"
        if self._mail is not None:
            card = format_letter_card(job, report, path.name, "")
            try:
                self._mail.send(
                    subject=f"Lettre — {job.company} · {job.title}",
                    body=f"{card}\n\n{report.get('text', '')}",
                    pdf=pdf,
                    filename=path.name,
                )
                email_status = "📧  Envoyée par e-mail"
            except DeliveryError as exc:
                email_status = f"📧  E-mail en échec : {exc}"
        try:
            self._attachments.send(
                pdf,
                path.name,
                f"✍️ Lettre prête · {job.company}",
                format_letter_card(job, report, path.name, email_status),
            )
        except DeliveryError as exc:
            log.warning("ntfy delivery of %s failed: %s", path.name, exc)

    def _cap_notice(self, now: datetime) -> None:
        today = now.date().isoformat()
        if self._store.get_meta(CAP_NOTICE_KEY) == today:
            return
        self._notifier.send(
            Message(
                title="Limite de lettres atteinte",
                body=f"{self._max_per_day} lettres sur les dernières 24 h. "
                "Réessaie plus tard.",
                priority=2,
                tags=("warning",),
            )
        )
        self._store.set_meta(CAP_NOTICE_KEY, today)
```

`intern_radar/letters/inbox.py`:

```python
"""Letter requests: the ntfy topic stream and the listener loop."""

import json
import logging
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx

from intern_radar.store import Store

log = logging.getLogger(__name__)

LAST_ID_KEY = "last_request_id"
FIRST_DELAY = 5
MAX_DELAY = 300


def parse_line(line: str) -> tuple[str, str] | None:
    try:
        event = json.loads(line)
    except ValueError:
        return None
    if not isinstance(event, dict) or event.get("event") != "message":
        return None
    return str(event.get("id", "")), str(event.get("message", "")).strip()


class RequestStream:
    def __init__(self, client: httpx.Client, server: str, topic: str) -> None:
        self._client = client
        self._url = f"{server.rstrip('/')}/{topic}/json"

    def messages(self, since: str | None) -> Iterator[tuple[str, str]]:
        # ntfy sends a keepalive every ~45 s; 90 s without data means a
        # dead connection.
        with self._client.stream(
            "GET",
            self._url,
            params={"since": since or "12h"},
            timeout=httpx.Timeout(20.0, read=90.0),
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                parsed = parse_line(line)
                if parsed:
                    yield parsed


def run_listener(
    stream: Any,
    handle: Callable[[str], object],
    store: Store,
    sleep: Callable[[float], None] = time.sleep,
    keep_going: Callable[[], bool] = lambda: True,
) -> None:
    delay = FIRST_DELAY
    while keep_going():
        try:
            for message_id, body in stream.messages(store.get_meta(LAST_ID_KEY)):
                try:
                    handle(body)
                except Exception:  # one bad request must not stop the listener
                    log.exception("letter request %s failed", message_id)
                store.set_meta(LAST_ID_KEY, message_id)
                delay = FIRST_DELAY
        except httpx.HTTPError as exc:
            log.warning("request stream lost (%s), retrying in %s s", exc, delay)
            sleep(delay)
            delay = min(delay * 2, MAX_DELAY)
```

- [ ] **Step 3: Verify and commit**

Run: `poetry run pytest -q && poetry run ruff check . && poetry run ruff format --check .` → pass. (The service test `test_generates_stores_and_delivers` reads `mail.sent[0]["subject"]`: `Recorder.send` stores keyword arguments, which `_deliver` uses for the mail.)

```bash
git add intern_radar/letters/service.py intern_radar/letters/inbox.py tests/letters/test_service.py tests/letters/test_inbox.py
git commit -m "feat(letters): handle letter requests from a secret ntfy topic"
```

---

### Task 10: CLI commands, systemd unit, docs

**Files:**
- Modify: `intern_radar/cli.py`, `tests/test_cli.py`, `README.md`
- Create: `deploy/intern-radar-letters.service`

**Interfaces:**
- Produces: `intern-radar letter JOB_ID`, `intern-radar listen`; `cli._letter_service(config_dir: Path, db: Path) -> tuple[LetterService, Store, httpx.Client, Profile]`.

- [ ] **Step 1: Failing tests** — append to `tests/test_cli.py`:

```python
def test_letter_requires_cv_url_and_contact(config_dir):
    result = runner.invoke(cli.app, ["letter", "some-job"])
    assert result.exit_code == 2
    assert "cv_url" in result.output and "contact" in result.output


def test_listen_requires_a_requests_topic(config_dir):
    (config_dir / "profile.yaml").write_text(
        PROFILE + "cv_url: https://cv\ncontact: {name: A B, location: P, phone: '1',"
        " email: e, linkedin: l, github: g}\n")
    result = runner.invoke(cli.app, ["listen"])
    assert result.exit_code == 2
    assert "requests_topic" in result.output


def test_letter_command_prints_the_pdf_path(config_dir, monkeypatch):
    (config_dir / "profile.yaml").write_text(
        PROFILE + "cv_url: https://cv\ncontact: {name: A B, location: P, phone: '1',"
        " email: e, linkedin: l, github: g}\n")

    class FakeService:
        def handle(self, job_id):
            return config_dir / f"{job_id}.pdf"

    monkeypatch.setattr(cli, "LetterService", lambda *a, **k: FakeService())
    result = runner.invoke(cli.app, ["letter", "job-1"])
    assert result.exit_code == 0
    assert "job-1.pdf" in result.output
```

Run: `poetry run pytest tests/test_cli.py -q` → FAIL (no such command `letter`).

- [ ] **Step 2: Implement** — in `intern_radar/cli.py` add imports

```python
from intern_radar.letters.cv import CvSource
from intern_radar.letters.delivery import GmailSender, NtfyAttachmentSender
from intern_radar.letters.inbox import RequestStream, run_listener
from intern_radar.letters.service import LetterService
from intern_radar.letters.writer import LetterWriter
```

constants `CV_CACHE = Path("data/cv-cache.json")`, `LETTERS_DIR = Path("data/letters")`, and:

```python
def _letter_service(config_dir: Path, db: Path):
    profile, _ = _load(config_dir)
    missing = [key for key in ("cv_url", "contact") if getattr(profile, key) is None]
    if missing:
        typer.echo(f"Configuration error: set {', '.join(missing)} in profile.yaml",
                   err=True)
        raise typer.Exit(2)
    client = make_client()
    store = _open_store(db, dry_run=False)
    cv = CvSource(client, profile.cv_url, CV_CACHE)
    backend = ClaudeCliBackend(model=profile.letter_model)

    def make_writer() -> LetterWriter:
        return LetterWriter(backend, cv.text(), profile.window_start,
                            profile.window_end, profile.min_months)

    mail = (
        GmailSender(profile.letters_email, profile.smtp_app_password)
        if profile.letters_email and profile.smtp_app_password
        else None
    )
    service = LetterService(
        store,
        make_writer,
        profile.contact,
        LETTERS_DIR,
        NtfyAttachmentSender(profile.ntfy_server, profile.ntfy_topic, client),
        mail,
        NtfyNotifier(profile.ntfy_server, profile.ntfy_topic, client),
        profile.max_letters_per_day,
    )
    return service, store, client, profile


@app.command()
def letter(
    job_id: str, config_dir: Path = CONFIG_DIR, db: Path = DB_PATH
) -> None:
    """Write, render and deliver the cover letter for one stored offer."""
    _setup_logging()
    service, store, client, _ = _letter_service(config_dir, db)
    try:
        path = service.handle(job_id)
    finally:
        store.close()
        client.close()
    if path is None:
        typer.echo("No letter produced (see logs).", err=True)
        raise typer.Exit(1)
    typer.echo(str(path))


@app.command()
def listen(config_dir: Path = CONFIG_DIR, db: Path = DB_PATH) -> None:
    """Wait for letter requests from the notification button (runs forever)."""
    _setup_logging()
    service, store, client, profile = _letter_service(config_dir, db)
    if not profile.requests_topic:
        typer.echo("Configuration error: set requests_topic in profile.yaml",
                   err=True)
        raise typer.Exit(2)
    stream = RequestStream(client, profile.ntfy_server, profile.requests_topic)
    try:
        run_listener(stream, service.handle, store)
    finally:
        store.close()
        client.close()
```

(The `listen` test hits the `requests_topic` check before any network use; the `letter` test replaces `LetterService` so nothing is fetched.)

- [ ] **Step 3: systemd unit** — `deploy/intern-radar-letters.service`:

```ini
[Unit]
Description=intern-radar: cover letters on demand
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/root/remote-claude/intern-radar
Environment=HOME=/root
Environment=PATH=/root/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/root/.local/bin/poetry run intern-radar listen
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 4: README** — add a "Cover letters" section after "How it works": the button, the flow (draft → ATS → anti-AI → fidelity → PDF → ntfy + e-mail), the profile keys (`requests_topic`, `cv_url`, `contact`, `letters_email`, `smtp_app_password`, `letter_model`, `max_letters_per_day`), the two commands, and the extra deployment line `systemctl enable --now intern-radar-letters.service` (link the unit like the others).

- [ ] **Step 5: Verify and commit**

Run: `poetry run pytest -q && poetry run ruff check . && poetry run ruff format --check .` → pass.

```bash
git add intern_radar/cli.py tests/test_cli.py deploy/intern-radar-letters.service README.md
git commit -m "feat(letters): add letter and listen commands and the systemd service"
```

---

### Task 11: Real check, PR, deployment

- [ ] **Step 1: Real letter** — pick an AI-relevant scored offer (`poetry run intern-radar list --min-score 0`), then fill in `config/profile.yaml`: `requests_topic` (`intern-radar-req-` + `secrets.token_urlsafe(12)`), `cv_url` (the Google Doc export link from the GitHub profile README), `letters_email`, `contact` (values from the CV). Run `poetry run intern-radar letter <job_id>`. Expected: a PDF path; the letter and card arrive on the phone. Read the PDF text back (`pypdf`) and check: 3 paragraphs, facts from the CV only, report sensible.
- [ ] **Step 2: Button path** — `curl -d "<job_id>" https://ntfy.sh/<requests_topic>` while `poetry run intern-radar listen` runs in the background; expected: the stored letter is re-delivered (no LLM call). Stop the listener.
- [ ] **Step 3: PR** — push `feature/19-cover-letters`, open a PR to `develop` closing #19 (body: summary, tests count, real letter check), wait for CI, rebase-merge, delete the branch.
- [ ] **Step 4: Deploy** — `git switch develop && git pull --ff-only && poetry install --only main`, link `deploy/intern-radar-letters.service` into `/etc/systemd/system/`, `systemctl daemon-reload && systemctl enable --now intern-radar-letters.service`, check `systemctl is-active` and `journalctl -u intern-radar-letters -n 20`.
