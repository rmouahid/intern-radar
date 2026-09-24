# intern-radar — Pipeline technical reference

Audience: engineers operating or extending intern-radar. Figures marked
**measured** come from the production VPS on 2026-09-24 (1 vCPU, 2 GB RAM,
Ubuntu 26.04); everything else is derived from the code at `develop`.

## 1. Overview

intern-radar is a single-user batch pipeline plus one long-running listener:

```
                     systemd timers (Europe/Paris)
            ┌──────────── every 2 h, 08:00–22:00 ────────────┐   21:00
            ▼                                                 │     ▼
  ┌──────────────────┐  ┌───────────┐  ┌──────────────┐  ┌────┴─────────┐  ┌────────┐
  │ 1. COLLECT        │→ │2. PRE-    │→ │3. SCORE (LLM) │→ │4. RANK +     │  │ DIGEST │
  │ 9 source plugins  │  │  FILTER   │  │ haiku, 10/call│  │   NOTIFY     │  │        │
  └──────────────────┘  └───────────┘  └──────────────┘  └──────────────┘  └────────┘
            │                 │                │                  │               │
            └───────────── SQLite (data/intern-radar.db) ─────────┴───────────────┘
                                                                 │ Telegram Bot API
                                                                 ▼
                                   phone ── tap "✍️ Lettre" ── getUpdates (long poll)
                                                                 │
                              intern-radar-letters.service (always on)
                         CV → draft → ATS → anti-AI → fidelity → PDF → sendDocument
```

| Unit | Type | Command | Schedule |
|---|---|---|---|
| `intern-radar-run` | oneshot | `intern-radar run` | 08,10,…,22:00 Europe/Paris, `Persistent=true` |
| `intern-radar-digest` | oneshot | `intern-radar digest` | 21:00 Europe/Paris, ordered after `run` |
| `intern-radar-letters` | simple, `Restart=always` | `intern-radar listen` | always on |

All outbound; no inbound port is opened. External dependencies: public job
board APIs, Adzuna (optional key), the `claude` CLI (headless, user
subscription), the Telegram Bot API, Gmail SMTP (optional), the CV PDF export
of a Google Doc.

## 2. Data model

One SQLite file, short autocommit transactions (`with self._db:` per write),
default 5 s busy timeout. Tables:

| Table | Key | Purpose |
|---|---|---|
| `jobs` | `id` (`<source>:<board>:<native id>`) | every internship-titled posting ever seen |
| `source_health` | company | current failure streak (`first_failure`, `last_error`, `alerted`) |
| `llm_health` | singleton | LLM failure streak |
| `letters` | job id | PDF path, report JSON (checks + letter text) |
| `meta` | key | listener offset (`last_update_id`), cap notice day |

Job lifecycle (`jobs.status` plus timestamps):

```
fetched ─┬─ pre-filter fails ─────────────► rejected   (description dropped)
         ├─ Adzuna copy of an ATS offer ──► duplicate  (description dropped)
         └─ passes ─► pending ─┬─ LLM answer ─► scored ─┬─ score NULL  → excluded, never sent
                               │                        ├─ ≥ 7.5       → notified_at
                               │                        └─ 5.5–7.5     → digested_at
                               └─ 3 answers without it ─► stays pending, no longer retried
```

Measured on the first day: 935 rows, 5.3 MB (descriptions of pending jobs
are the bulk). Growth follows new postings (~30/day), i.e. well under
1 MB/week.

## 3. Stages

### 3.1 Collection (`intern_radar/sources/`)

66 companies in `config/companies.yaml` (tiers: 8 S, 29 A, 28 B, plus the
Adzuna catch-all). 46 have a live feed, 19 have none and rely on Adzuna.

| Plugin | Endpoint | Paging / caps | Detail call |
|---|---|---|---|
| greenhouse (22) | `boards-api.greenhouse.io/v1/boards/{board}/jobs` | full list | 1 per **new** internship |
| workday (10) | `{host}/wday/cxs/{tenant}/{site}/jobs` (POST, `searchText=intern`) | 20/page, **5 pages max** | 1 per new internship |
| ashby (7) | `api.ashbyhq.com/posting-api/job-board/{org}` | full list | none |
| lever (2) | `api.lever.co/v0/postings/{site}` | full list | none |
| smartrecruiters (2) | `…/companies/{id}/postings?q=intern` | 100/page, 3 pages | 1 per new internship |
| workable (1) | widget API `?details=true` | full list | none |
| amazon | `amazon.jobs/en/search.json?base_query=intern` | 100/page, 5 pages | none |
| microsoft | `apply.careers.microsoft.com/api/pcsx/search` | 10 pages | none (no description available) |
| adzuna | 12 countries, `what=intern`, `max_days_old=7` | 1 page × 50 per country | none |

Common behaviour:

- One shared `httpx.Client`: 20 s timeout, `User-Agent` identifying the
  project, and a request hook that keeps **≥ 1 s between two requests to the
  same host** (politeness; also keeps Telegram near 1 msg/s).
- Plugins keep only titles matching the internship regex and skip ids
  already in the database, so detail calls are paid once per posting.
- Per-posting isolation: `collect()` converts each posting separately;
  a malformed item or a failed detail call is logged and skipped (it is not
  stored, so it is retried next run). Only a failing *list* call fails the
  source.
- HTTP errors are reported as `METHOD base-url: HTTP <status>` — query
  strings (Adzuna key) never reach logs, SQLite or alerts; the `httpx`
  request logger is silenced.

Measured: first run (cold database, ~900 detail calls) 18 min; steady-state
collection ~2 min.

### 3.2 Pre-filter (`prefilter.py`, pure)

- Title: `\b(interns?|internships?|co-?ops?|stagiaires?|trainees?|placements?)\b`
  (whole words, so *Internal*/*International* do not match).
- Location: rejected only when every place listed is French (separators
  `; , | / & and or`; neutral parts such as *Remote*, *EU*, *Île-de-France*
  are ignored; "excluding France" is not French).
- Adzuna offers whose company and title match an ATS offer are stored as
  `duplicate`.

### 3.3 LLM scoring (`scorer.py`)

- Backend: `claude -p --model haiku --output-format json --json-schema …
  --tools "" --no-session-persistence --strict-mcp-config`. No tools and no
  MCP servers: a prompt injection in a posting can only change the answer,
  never execute anything.
- Batches of 10 jobs; descriptions truncated to 3,000 characters; jobs are
  numbered 1..n in the prompt (long source ids were mangled by the model).
- Every item is validated (types, enums, 0–10 range); invalid or missing
  items stay `pending` and count an attempt; after 3 attempts the job is no
  longer retried.
- A CLI failure (non-zero exit, `is_error`, invalid JSON, timeout 600 s)
  raises `LLMError`: the whole run stops scoring, **no attempt is counted**,
  jobs are retried next run. The error message carries the envelope's
  `api_error_status`, `subtype` and `result`.
- Caps per run: `max_llm_batches_per_run` (5) × 10 jobs. The backlog is
  ordered tier S → A → B → unlisted, newest first.

### 3.4 Ranking (`ranking.py`, pure)

```
excluded (score NULL) if: not an internship, dates incompatible, PhD only,
                          language other than EN/ES/FR, AI relevance < 6
score = 0.5·tier + 0.3·relevance + 0.2·dates      (tier S10 A8 B6 unlisted4;
                                                   dates fits10 unknown6 short4)
      − 2 if local students only                   rounded to 0.1
```

Thresholds: ≥ 7.5 immediate, 5.5–7.5 digest (both configurable).

### 3.5 Notifications (`notifier.py`, `telegram.py`)

- HTML messages (only `<b>`, `<i>`, `<a>`; every dynamic value
  `html.escape`d, including `href`), link previews off.
- Offer: company, title, location, score, dates, visa note, summary (fields
  capped: 80/200/100/300/500 characters), buttons *Voir l'offre* (only for
  `http(s)` URLs) and *Lettre de motivation* (`callback_data = L:<rowid>`,
  within Telegram's 64-byte limit).
- Digest: ≤ 15 offers (keeps the rendered text under 4,096), silent.
- Alerts (silent): a source failing for 3 consecutive days, the LLM failing
  for 1 day; each alerted once per streak.
- Delivery semantics: an offer is marked `notified_at` only after Telegram
  answers `ok`. Transient failures (network, 429 after one retry, 5xx) stop
  the notification step and everything is retried next run. Permanent
  rejections (4xx other than 429) are logged, marked and skipped so that one
  bad message cannot block later ones. At most `max_immediate_per_run` (10)
  offers per run.

### 3.6 Cover letters (`letters/`)

Triggered by a button tap:

1. `getUpdates` long poll (50 s, read timeout 60 s, `allowed_updates =
   ["callback_query"]`), offset persisted in `meta`; backoff 5 s → 300 s on
   errors, reset after any successful poll.
2. A tap is accepted only if both the chat id and the sender id equal
   `telegram_chat_id`; it is answered at once ("⏳ Lettre en préparation…").
3. Stored letter present → re-sent, no LLM call. Daily cap
   (`max_letters_per_day`, 10) → one notice per day.
4. CV text from the Google Doc PDF export (`pypdf`), cached 24 h; a stale
   cache is used when the download fails.
5. LLM (sonnet, `--effort low`), 2 to 4 calls:
   - **draft + keywords** in one call: 3 paragraphs with the CV as sole source
     of facts, the offer wrapped in `<offer>` as untrusted data, and the
     offer's 10–15 ATS keywords with an `in_cv` flag (ignored when the offer
     has no description);
   - **ATS pass**, only if CV-backed keywords are missing, and **anti-cliché
     pass**, always; a second anti-cliché pass only if a blacklisted phrase
     remains. These passes return **edits** (`{"before", "after"}`, exact
     substrings), not a new letter; `apply_edits` replaces each `before`
     once (whitespace-tolerant), skips edits that do not match or would
     empty a paragraph, and counts them (`edits_failed`, shown in the
     caption).
6. Pure checks: keyword coverage, blacklist, fidelity (proper nouns — with
   accented capitals — and "number + unit" not found in CV/offer),
   keywords the model judged "in the CV" without literal evidence.
7. PDF (`fpdf2`, A4, Helvetica, Latin-1 after NFKC and typographic mapping;
   unknown characters become spaces and are reported); font shrinks
   11 → 10.5 → 10 pt to fit one page; the model's signature is stripped from
   the closing. Stored under `data/letters/<sha1(job id)[:10]>/`.
8. `sendDocument` with an HTML caption built by dropping whole optional
   sections until the *visible* text fits 1,024 characters; if Telegram
   rejects it, the PDF is re-sent with a plain-text caption; if that fails
   too, a "Lettre non envoyée" message is sent. Optional Gmail copy (SMTP
   over SSL, app password).

Any exception while writing a letter sends "❌ Lettre non générée" with the
reason; the listener never stops on a bad tap (the offset still advances).

## 4. Reliability — failure modes

| Failure | Detection | Behaviour | Recovery |
|---|---|---|---|
| One job board down / schema change | list call raises | source skipped this run, others continue | automatic next run; alert after 3 days |
| One posting malformed / detail 404 | per-item exception | posting skipped, not stored | retried next run |
| Adzuna keys missing | `SourceError` | source fails every run | add keys; alert after 3 days |
| LLM quota exhausted / API error | `LLMError` | scoring stops, jobs stay pending, no attempt counted | next run; alert after 1 day |
| LLM returns partial / invalid items | schema + Python validation | valid items saved, others retried (≤ 3) | automatic |
| Telegram unreachable / 429 / 5xx | `TelegramError` | notification step stops, nothing marked | next run |
| Telegram rejects one message (4xx) | `NotifyError(permanent)` | logged, marked, skipped | fix the formatter; offer visible in `intern-radar list` |
| Run killed (timeout 1 h, reboot) | systemd | each write is committed; at most the current company is refetched | `Persistent=true` catches missed runs |
| Listener crash | systemd `Restart=always` (10 s) | resumes from persisted offset | automatic |
| CV download fails | `CvError` / stale cache | stale text used, else failure message | automatic |
| Duplicate tap | stored letter | PDF re-sent (known: twice on a fast double tap) | none needed |

Delivery guarantees:

- Offers: **at least once per offer**, at most `max_immediate_per_run` per
  run; duplicates are possible only if Telegram accepted a message but the
  answer was lost (the offer is then re-sent next run).
- Letters: **at least once per tap** (offset stored after handling).
- Digest: one message per evening when there is something to send; not
  sent twice (marked only after success).

## 5. Robustness guarantees

- **Idempotent collection**: ids are stable; `INSERT OR IGNORE`; known ids
  are skipped before any detail call.
- **Bounded work per run**: pages per source, 50 LLM-scored jobs, 10
  immediate notifications; worst case ~10 min steady state, 1 h hard timeout.
- **Bounded message sizes**: every field sent to Telegram is capped;
  captions are rebuilt, never cut inside a tag or an entity.
- **Secrets**: `profile.yaml` is gitignored; the bot token lives only in
  request URLs, errors are raised `from None` and carry method + status;
  HTTP query strings are never logged; SMTP password only reaches `login`.
- **Least privilege for the LLM**: no tools, no MCP, strict JSON schema.
- **Single-tenant access control**: button taps from any other chat are
  ignored without an answer.

## 6. Limits and known gaps

Coverage:

- 19 watched companies (Google, Meta, Apple, Mistral, Goldman, Citadel…)
  have no public feed and are only visible through Adzuna, which needs keys
  and only sees what aggregators index.
- Workday searches are relevance-sorted and capped at 100 results per
  tenant; Amazon at 500; Microsoft offers have no description (the LLM
  scores title and location only, ATS step skipped for letters).
- Pre-filter heuristics: a French city name inside a non-French location
  string ("Paris, Texas") is treated as French; "Placement" titles can be
  non-internships (the LLM confirms).

Judgement:

- The LLM decides internship status, dates and eligibility from free text.
  Observed: 39 % of assessments have `dates_fit = unknown`; a "Class of
  2029" Amazon Japan posting scored 8.5 although it likely targets another
  graduation year. Scores are a triage aid, not a decision.
- Scoring is not deterministic: the same 10 offers scored twice agreed on
  internship status, dates and eligibility for 7 of 10, and `ai_relevance`
  moved by 0.7 point on average. An offer near a threshold can land on
  either side of it.
- Letters come out shorter than the requested ~300 words (202–276 words
  measured); the one-page layout is unaffected.
- `ai_relevance < 6` excluded 91 of the first 100 scored offers (the backlog
  starts with tier-S Amazon postings, many non-technical).
- Fidelity checks do not verify sentence-initial words; skills the model
  wrongly marks as "in the CV" are reported, not removed.

Platform:

- Single user, single chat; no group support.
- Letters are generated synchronously: a second tap waits for the first
  letter (its answer may arrive late).
- The job reference is SQLite's implicit `rowid`; a manual `VACUUM` could
  renumber rows and make old buttons point to other offers.
- Telegram limits: 4,096 characters per message, 1,024 per caption, 64 bytes
  of callback data, ~1 message/s per chat.
- The scoring depends on the `claude` CLI being logged in on the VPS; its
  subscription quota is shared with interactive use.
- Adzuna free tier: 12 requests per run × 8 runs = 96/day; check the
  account limits before relying on it.

## 7. LLM usage and cost (measured)

Numbers from the CLI's JSON envelope (`usage`, `output_tokens_details`,
`total_cost_usd`). Input = fresh + cache-creation + cache-read tokens (the
CLI's own system prompt, ~2.5 k tokens, is served from cache on every call).
Reasoning ("thinking") tokens are billed as output. `total_cost_usd` is the
**API-equivalent** price: with a subscription it is consumed quota, not
billed money; single calls also vary with cache state, so compare tokens
first.

| Operation | Model / effort | Calls | Input | Output (of which reasoning) | Latency | API-equiv. |
|---|---|---|---|---|---|---|
| Score 10 offers | haiku / default | 1 | 15.3 k | 7.9–10.7 k (≈ 83 %) | 81–107 s | $0.072 |
| Letter, v1 (draft, keywords, ATS rewrite, anti-AI rewrite) | sonnet / default | 4 | 28.2 k | 5.7 k | 56 s | $0.141 |
| Letter, v2 (draft+keywords, ATS edits, anti-AI edits) | sonnet / default | 3 | 22.4 k | 4.7 k | 46 s | $0.127 |
| **Letter, v2 (current)** | **sonnet / low** | **3** | **22.7 k** | **2.25 k (0.4 k)** | **25 s** | **$0.084** |

Same NVIDIA offer for every letter row. v1 → current: output −61 %,
latency −56 %, API-equivalent −40 %. The largest single lever was
reasoning: the draft call alone went from 2,779 output tokens (1,770
reasoning, 24.9 s) to 952 (0 reasoning, 9.7 s) with comparable text; moving
from full rewrites to edits saved one call and ~20 % of input.

Projections (current configuration):

| Scenario | Batches/day | Scoring | Letters | Total/day (API-equiv.) |
|---|---|---|---|---|
| Backlog (first 2–3 days) | 5 × 8 = 40 | $2.9, ~60 min LLM time | — | ~$3/day, then drops |
| Steady state (~30 new postings/day, 99 % pass the pre-filter) | ~3 | $0.22 | 2 letters: $0.17 | **~$0.39/day ≈ $12/month** |
| Cap (all limits reached) | 40 | $2.9 | 10 letters: $0.84 | ~$3.7/day |

Observations and levers:

- Scoring output is ~83 % reasoning (6.5–7.4 k of 7.9–8.9 k tokens per
  batch). `--effort low` had no effect on haiku in the same measurement, so
  `llm_effort` stays unset; reducing reasoning for scoring would need
  another model/effort combination and a quality check against the
  run-to-run variance above.
- Descriptions are truncated at 3,000 characters for scoring and 6,000 for
  letters; lowering them reduces input linearly.
- A second tap on the same offer costs nothing (stored letter).
- Cost per notified offer depends on the pass rate: with the current
  filters about 7 offers per 100 scored reached the immediate band.

## 8. Operations

```bash
systemctl list-timers 'intern-radar*'
systemctl status intern-radar-letters
journalctl -u intern-radar-run -n 50            # last run: fetched=… scored=… errors=…
tail -f logs/intern-radar.log                   # all components (logrotate weekly, 8 kept)
poetry run intern-radar check-sources           # which feeds answer
poetry run intern-radar run --dry-run           # full pass, in-memory DB, prints messages
poetry run intern-radar list --min-score 6      # stored offers
poetry run intern-radar letter <job_id>         # write/re-send one letter
```

Runbook:

- *No notifications*: check the last `fetched=… errors=…` line; `LLM:` errors
  mean the CLI is logged out or out of quota (`claude -p` by hand);
  `telegram:` errors with 401 mean the token was revoked.
- *Letter button spins forever*: `systemctl status intern-radar-letters`;
  the listener must run for taps to be answered.
- *A source keeps failing*: `check-sources`, then fix the board id in
  `companies.yaml` or set `source: none`.
- *Changing the bot*: update `telegram_token`/`telegram_chat_id` and delete
  the `last_update_id` row in `meta` (update ids are per bot).

## 9. Quality gates

- 208 tests (`pytest`), offline: source plugins run against payloads that
  mirror the real API responses (captured on 2026-09-24); LLM, Telegram and
  SMTP are replaced by fakes; SQLite runs in memory.
- `ruff check` + `ruff format --check` in GitHub Actions on every PR.
- Every feature went through a written spec, a plan, test-first
  implementation and an independent whole-branch review; review findings
  were fixed with a failing test first (specs and plans in
  `docs/superpowers/`).
- Manual end-to-end checks against real services before each merge (job
  boards, LLM, Telegram, PDF read back with `pypdf`).
