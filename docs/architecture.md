# Architecture and design decisions

This document explains how intern-radar is built and why. The
stage-by-stage behaviour, failure modes and measurements are in
[pipeline.md](pipeline.md); settings are in
[configuration.md](configuration.md).

## 1. Context and constraints

| Constraint | Consequence |
|---|---|
| One user, one phone | no accounts, no web UI; a messaging bot is the interface |
| A small VPS (1 vCPU, 2 GB RAM) | no browser automation, no local model; plain HTTP + a hosted LLM |
| Near-zero budget | free APIs, the LLM through an existing subscription, no paid push service |
| Unattended operation | every failure must be isolated, retried or reported, never silent |
| Public repository | secrets only in a gitignored file; nothing personal in code or history |
| Target offers are on company career pages | adapters per job-board platform rather than aggregators only |

Quality goals, in order: **correct triage** (no missed good offer, few
false alarms), **reliability** (no silent failure), **cost control** (LLM
calls bounded and measured), **maintainability** (small modules, offline
tests).

## 2. Components

```
                         ┌──────────────── cli.py (Typer) ───────────────┐
                         │  run · digest · list · check-sources ·        │
                         │  letter · listen                              │
                         └──────┬──────────────────────────────┬────────┘
                                │                              │
                      ┌─────────▼─────────┐          ┌─────────▼─────────┐
                      │   pipeline.py      │          │ letters/inbox.py   │
                      │   one scheduled run│          │ long-poll listener │
                      └─┬───┬───┬───┬───┬─┘          └─────────┬─────────┘
                        │   │   │   │   │                      │
     ┌──────────────────┘   │   │   │   └──────────┐  ┌────────▼─────────┐
     ▼                      ▼   │   ▼              ▼  │ letters/service.py│
 sources/*  ──► prefilter.py    │ ranking.py   notifier.py ◄──┤ writer · checks  │
 (http.py)                      ▼                  │        │ pdf · cv · delivery│
                           scorer.py               ▼        └────────┬─────────┘
                        (LLM CLI backend)     telegram.py ◄──────────┘
                                                   │
                 store.py (SQLite) ◄───────── used by pipeline, service, inbox
```

Module rules:

- **Pure core**: `prefilter`, `ranking`, `letters/checks` and the message
  formatters have no I/O and are tested exhaustively.
- **Adapters at the edge**: `sources/*`, `scorer.ClaudeCliBackend`,
  `telegram.TelegramClient`, `letters/delivery.GmailSender` and
  `letters/cv.CvSource` are the only modules that talk to the outside world;
  each sits behind a small protocol (`Source`, `LLMBackend`, `Notifier`,
  `DocumentSender`) that tests replace with fakes.
- **Orchestrators**: `pipeline.Pipeline` and `letters/service.LetterService`
  receive their collaborators and a clock by injection; they hold the
  failure policies.
- **One persistence module**: `store.Store` owns the schema; every other
  module goes through its methods.

## 3. Design decisions

Each decision lists the alternatives considered and the trade-off accepted.

### D1 — Job-board APIs instead of scraping

Greenhouse, Lever, Ashby, Workable and SmartRecruiters expose public JSON
boards; Workday, Amazon and Microsoft expose the JSON APIs their own career
sites use. Adzuna covers the rest through an official API.

- *Rejected*: HTML scraping (brittle, heavier), LinkedIn/Indeed scraping
  (terms of service, account risk), browser automation (does not fit 2 GB).
- *Trade-off*: companies without a usable feed (19 of 66) are only seen
  through Adzuna. Each is marked `source: none` so coverage is explicit.

### D2 — Rules before the LLM

A pure pre-filter keeps internship titles (whole-word regex) and drops
France-only locations and duplicates before any LLM call; adapters also
skip already-known ids before fetching details.

- *Why*: the LLM is the slow and costly stage (~9 s per offer). A single
  board lists hundreds of jobs (Databricks 883, OpenAI 828, Anthropic 630
  when measured) of which a handful are internships; the first run kept 928
  internship-titled postings across all feeds.
- *Trade-off*: regexes miss unusual titles; the LLM then confirms internship
  status on what passes.

### D3 — The LLM judges, Python scores

The LLM returns facts about an offer (internship or not, AI relevance 0–10,
dates fit, eligibility, visa note, language, summary) under a JSON schema;
the final score is a weighted sum computed in Python with explicit
exclusions.

- *Rejected*: asking the LLM for a score directly (opaque, drifts between
  calls, impossible to re-weight without re-scoring).
- *Why*: weights and thresholds are configuration; changing them needs no
  LLM call; the formula is unit-tested. Company prestige (the candidate's
  first criterion) is data (`tier`), not an LLM opinion.
- *Measured trade-off*: the LLM's judgements vary between calls (7/10
  agreement on categorical fields); the formula cannot remove that noise,
  only bound its effect.

### D4 — A headless LLM CLI instead of an API client

`claude -p --output-format json --json-schema … --tools "" --strict-mcp-config`
runs with the logged-in subscription.

- *Why*: no API key to manage or bill; structured output validated by the
  CLI; tools and MCP servers disabled, so text in a job posting can never
  trigger an action.
- *Trade-off*: one process per call (~2.5 k tokens of CLI system prompt,
  served from cache), shared quota with interactive use, dependency on the
  CLI's JSON envelope (`structured_output`, `usage`). The backend is one
  class behind `LLMBackend`; an API client would replace it without touching
  callers.

### D5 — SQLite as the single source of truth

One file holds jobs, assessments, notification timestamps, health streaks,
letters and listener state.

- *Why*: zero operations, transactional, enough for thousands of rows;
  every state change is one short transaction, so a killed run loses at
  most the company being fetched.
- *Design*: stable job ids (`source:board:native_id`) make collection
  idempotent; status + timestamps (`notified_at`, `digested_at`) make
  delivery retriable without duplicates.
- *Trade-off*: two processes (timer run, listener) share the file; writes
  are short and the 5 s busy timeout absorbs contention.

### D6 — systemd timers instead of cron

- *Why*: the VPS runs in UTC while the schedule is Europe/Paris
  (`OnCalendar=… Europe/Paris` handles DST); a oneshot unit never overlaps
  itself; `Persistent=true` catches runs missed during downtime; journald
  keeps the output.

### D7 — Telegram, long polling, no inbound port

The first version pushed through ntfy.sh. In production the anonymous
publishing quota blocked the server's IP after a dozen messages (HTTP 429),
which silenced every notification. The channel moved to a Telegram bot.

- *Why Telegram*: free at this volume, HTML formatting, inline buttons,
  documents up to 50 MB, a stable Bot API.
- *Why long polling* (`getUpdates`) rather than a webhook: no domain, TLS
  certificate or open port on the VPS; the listener only makes outbound
  requests.
- *Security*: button taps are accepted only when both the chat and the
  sender match the configured chat id.
- *Constraint handled*: callback data is limited to 64 bytes while Workday
  ids exceed it; buttons carry `L:<rowid>` instead.

### D8 — Failure isolation at every level

| Level | Mechanism |
|---|---|
| Source | exception caught per company; failure streak recorded; alert after 3 days |
| Posting | `collect()` converts postings one by one; a bad one is skipped and retried next run |
| LLM batch | `LLMError` stops scoring without consuming retries; invalid items retried ≤ 3 times |
| Message | transient errors stop the step (retried next run); permanent 4xx rejections are skipped so they cannot block later messages |
| Letter | any exception reaches the user as a failure message; a rejected caption is resent as plain text |
| Process | systemd restarts the listener; runs are bounded (pages, batches, notifications, 1 h timeout) |

### D9 — Cover letters: facts from the CV, edits instead of rewrites

- The CV (exported from the candidate's Google Doc) is the **only** source
  of facts; the offer is wrapped in `<offer>` and declared untrusted data.
- Python checks what the LLM cannot be trusted with: keyword coverage,
  blacklisted phrases, proper nouns and "number + unit" absent from the CV
  and the offer, keywords the model claims are "in the CV" without literal
  evidence. Findings are reported with the PDF, never silently fixed.
- **v1** used four calls (draft, keyword extraction, full ATS rewrite, full
  anti-cliché rewrite). Measurements showed output tokens dominated cost and
  that 64 % of the draft's output was model reasoning. **v2** drafts and
  extracts keywords in one call, turns both passes into
  `{"before", "after"}` edits applied in Python (unmatched edits are
  skipped and counted), and runs the letter model at low effort: output
  −61 %, latency 56 s → 25 s, API-equivalent −40 % on the same offer.

### D10 — PDF with a core font

- `fpdf2` with Helvetica needs no font files on a minimal server.
- *Constraint*: core fonts are Latin-1. Text is NFKC-normalised, common
  typography is mapped (’ “ ” — … œ €), anything else becomes a space and is
  reported. Found in production: a Japanese title's fullwidth brackets
  glued words together before this rule.
- One-page guarantee: the font shrinks 11 → 10.5 → 10 pt before a second
  page is accepted and reported.

### D11 — Secrets and privacy

- `config/profile.yaml` (bot token, chat id, SMTP password, contact details)
  is gitignored; a documented `profile.example.yaml` is versioned.
- The bot token is part of every Telegram URL: errors carry the method and
  HTTP status only and are raised without their cause; the `httpx` request
  logger is silenced (it also hides the Adzuna key in query strings).
- Letters, the CV cache and the database live in the gitignored `data/`.

## 4. Evolution

| Step | Change | Driver |
|---|---|---|
| Core pipeline | 9 adapters, pre-filter, LLM triage, ntfy notifications, systemd | initial design |
| AI relevance floor | offers below 6/10 relevance never notified | first real run notified finance/design internships at tier-S companies |
| French card layout | airier message format, French labels | user feedback on the phone |
| Cover letters | on-demand letters with ATS, anti-cliché and fidelity checks | turn a notification into an application |
| Telegram | ntfy replaced, buttons and documents | ntfy.sh anonymous quota blocked the VPS |
| Lean letters | one draft call, JSON edits, low effort | measured token usage |

Each step went through a written design, a plan, test-first implementation
and an independent review of the whole branch; findings were fixed with a
failing test first.

## 5. Extension points

- **New job board**: one module in `sources/` implementing
  `fetch(company, known_ids) -> list[Job]`, registered in
  `sources/__init__.py` (see [development.md](development.md#adding-a-source)).
- **Another LLM**: implement `LLMBackend.complete(prompt, schema) -> dict`.
- **Another channel**: implement `Notifier.send(Message)` (and
  `DocumentSender.send_document` for letters).
- **Scoring policy**: weights, thresholds and the relevance floor are
  configuration; exclusions live in `ranking.py`.
