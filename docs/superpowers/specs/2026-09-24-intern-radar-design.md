# intern-radar — Design

Date: 2026-09-24
Status: draft, awaiting review

## 1. Goal

Automatically detect internship offers published by top AI/tech companies
(and large groups with strong AI teams) outside France, score them against
the candidate's profile, and push the relevant ones to the candidate's
phone through ntfy.

### Candidate constraints

- Internship window: **2027-03-08 → 2027-08-31**.
- Minimum duration: **4 months**; the longer the better (max ≈ 5.8 months).
- Location: **anywhere outside France**. USA, UK, Canada, Singapore and
  European offices are weighted equally — only company size/prestige
  matters.
- Field: AI / ML engineering (RAG, LLMs, agents, MLOps, data).
- Languages: English (C2), Spanish (B2), French (native).
- Purpose: a prestigious company that boosts the application for a top
  end-of-studies internship the following year.

### Success criteria

- An offer matching the criteria at a listed company triggers a
  notification within a few hours of being published (next run).
- Few false positives: non-internships, PhD-only roles, incompatible dates
  and roles located in France are never notified.
- The candidate knows exactly which companies are covered and by which
  source (`check-sources`).
- Running costs: no paid API; LLM calls go through the existing Claude
  subscription (`claude -p`) and stay low thanks to rule-based
  pre-filtering.

### Out of scope (v1)

- Reading LinkedIn / Indeed / Glassdoor email alerts from Gmail (planned
  v2, via IMAP and a Gmail app password).
- Self-hosted ntfy server (v1 uses `ntfy.sh` with a secret topic).
- Any web UI; applying to offers automatically.

## 2. Architecture

A Python CLI application (Poetry, Typer), run by cron on the VPS.

```
cron (every 2h, 08:00–22:00)          cron (21:00)
        │                                  │
        ▼                                  ▼
  intern-radar run                  intern-radar digest
        │                                  │
  1. FETCH      sources/*            read SQLite → jobs in the
  2. NORMALIZE  → Job                digest band not yet sent
  3. DEDUP      SQLite               → one ntfy summary
  4. PREFILTER  rules
  5. SCORE      claude -p (batched)
  6. NOTIFY     ntfy if ≥ threshold
```

### Modules

| Module | Responsibility | Depends on |
|---|---|---|
| `models.py` | `Company`, `RawJob`, `Job`, `Assessment`, `ScoredJob` dataclasses | — |
| `config.py` | load and validate `companies.yaml` and `profile.yaml` | models |
| `sources/` | one plugin per source type: `fetch(company) -> list[Job]`; no other logic | models, httpx |
| `store.py` | SQLite: seen jobs, assessments, scores, notification state, source health | models |
| `prefilter.py` | pure rule-based filter | models |
| `scorer.py` | builds prompts, calls the LLM backend, parses structured output | models, `LLMBackend` |
| `ranking.py` | pure final-score computation and exclusions | models |
| `notifier.py` | formats and sends ntfy messages | httpx |
| `pipeline.py` | orchestrates one run | all of the above |
| `cli.py` | Typer commands | pipeline, store, notifier |

Each unit is testable in isolation; network and LLM access sit behind
small interfaces (`Source`, `LLMBackend`, `Notifier`) that tests replace
with fakes.

## 3. Sources and company list

### `config/companies.yaml` (versioned, public)

```yaml
- name: Anthropic
  tier: S
  source: greenhouse
  board: anthropic
- name: NVIDIA
  tier: S
  source: workday
  tenant: nvidia
  site: NVIDIAExternalCareerSite
  host: nvidia.wd5.myworkdayjobs.com
- name: Meta
  tier: S
  source: none        # no usable feed; covered only by Adzuna
```

Tiers:

- **S** — Google/DeepMind, Meta, Microsoft, Apple, Amazon, NVIDIA,
  OpenAI, Anthropic.
- **A** — e.g. Mistral, Cohere, Databricks, Scale AI, Hugging Face,
  Stripe, Palantir, Tesla, ByteDance, IBM Research; Jane Street, Citadel,
  Two Sigma, Goldman Sachs, JP Morgan; McKinsey QuantumBlack, BCG X.
- **B** — e.g. Salesforce, Snowflake, Adobe, Uber, Spotify, Qualcomm,
  DeepL, ElevenLabs; Grab, Sea; Shopify; Airbus, Siemens.

Target ≈ 80 companies. The exact source of each company is verified
during implementation; companies without a usable feed get
`source: none`.

### Source plugins

| Plugin | Endpoint type |
|---|---|
| `greenhouse` | `boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true` |
| `lever` | `api.lever.co/v0/postings/{company}?mode=json` |
| `ashby` | `api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=false` |
| `workable` | `apply.workable.com/api/v1/widget/accounts/{account}` |
| `smartrecruiters` | `api.smartrecruiters.com/v1/companies/{id}/postings` |
| `workday` | `{host}/wday/cxs/{tenant}/{site}/jobs` (POST, paginated, search text "intern") |
| custom portals | one plugin per giant (Google, Amazon, Microsoft…) where a stable JSON endpoint exists |
| `adzuna` | Adzuna API, countries US, GB, CA, SG and non-French European countries, query "AI intern" / "machine learning intern"; jobs attributed to a listed company when the employer name matches, otherwise tier "unlisted" |

Every plugin returns normalized `Job` objects:
`id` (`{source}:{company}:{native_id}`), `company`, `tier`, `title`,
`location`, `url`, `description` (plain text), `posted_at` (optional),
`source`.

HTTP: `httpx` with a 20 s timeout, a descriptive User-Agent, and at most
one request per second per host.

## 4. Pre-filter

Pure function, no LLM. A job passes if all of:

1. Title matches `\b(intern|internship|co-?op|stagiaire|trainee|placement)\b`
   (case-insensitive, whole words, so "Internal"/"International" do not
   match).
2. Location is not in France (matches on "France", "Paris", and the main
   French cities; remote roles restricted to France are excluded).
3. Job id is not already in the store.

## 5. Scoring

### LLM assessment

`claude -p --model haiku --output-format json --json-schema <schema>`,
batches of up to 10 jobs, descriptions truncated to 3,000 characters.
The prompt contains the candidate summary from `profile.yaml`
(skills, projects, window, languages) and the jobs.

Per job the LLM returns:

| Field | Values |
|---|---|
| `is_internship` | bool |
| `ai_relevance` | int 0–10 |
| `dates_fit` | `fits` / `too_short_extendable` / `incompatible` / `unknown` |
| `eligibility` | `ok` / `phd_only` / `local_students_only` / `unknown` |
| `visa_note` | short text |
| `language_ok` | bool (false if a language other than EN/ES/FR is required) |
| `summary` | one sentence |

`dates_fit` definitions, given the 2027-03-08 → 2027-08-31 window:
`fits` = can start in the window and last ≥ 4 months within it;
`too_short_extendable` = starts in the window but lasts < 4 months
(e.g. a 12-week summer internship); `incompatible` = cannot start in the
window (e.g. Jan–Apr co-op, fall internship); `unknown` = not stated.

The LLM call sits behind an `LLMBackend` interface (`ClaudeCliBackend`
in production). The response is validated against the schema; a job
missing from the answer, or a batch whose call fails (non-zero exit,
quota exhausted, invalid JSON), stays in state `pending` and is retried
on the next run.

### Final score (pure Python, `ranking.py`)

Hard exclusions (stored, never notified): `is_internship = false`,
`dates_fit = incompatible`, `eligibility = phd_only`,
`language_ok = false`.

Otherwise:

```
score = 0.5 * tier_points + 0.3 * ai_relevance + 0.2 * dates_points
tier_points:  S=10, A=8, B=6, unlisted=4
dates_points: fits=10, unknown=6, too_short_extendable=4
score -= 2 if eligibility == local_students_only
```

Examples: Google ML intern, dates fit, relevance 9 → 9.7;
Stripe SWE intern, dates unknown, relevance 4 → 6.4;
unlisted company AI intern, dates unknown, relevance 9 → 5.9.

Thresholds (configurable in `profile.yaml`):
score ≥ 7.5 → immediate notification; 5.5 ≤ score < 7.5 → evening digest;
below 5.5 → stored only.

## 6. Notifications

ntfy over HTTPS to `https://ntfy.sh/<secret topic>` (topic in
`profile.yaml`).

- **Immediate** (priority high, tag 🔥): title
  `[S] Google DeepMind — Research Engineer Intern`; body with location,
  score, `dates_fit`, `visa_note`, `summary`; a "View offer" action
  button opening the job URL.
- **Digest** (21:00, priority default): list of digest-band jobs scored
  since the last digest, sorted by score; nothing is sent if empty.
- **System alerts** (priority low): a source failing for 3 consecutive
  days; LLM backend unavailable for a whole day.

A notification is marked as sent in the store only after ntfy returns a
2xx response; failures are retried on the next run.

## 7. CLI

| Command | Purpose |
|---|---|
| `intern-radar run [--dry-run]` | one full pass (dry run: no ntfy, prints instead) |
| `intern-radar digest [--dry-run]` | send the evening digest |
| `intern-radar check-sources` | fetch every company, print job/internship counts and errors; validates `companies.yaml` |
| `intern-radar list [--min-score N]` | print stored scored jobs |

## 8. Error handling

- One failing source (timeout, HTTP error, schema change) is logged, its
  failure recorded in the store, and the run continues.
- LLM failures leave jobs `pending` (see §5).
- ntfy failures leave notifications unsent (see §6).
- A `flock` lock prevents overlapping runs.
- Logs go to `logs/intern-radar.log`, rotated by logrotate.

## 9. Configuration

- `config/companies.yaml` — versioned.
- `config/profile.yaml` — **not versioned** (gitignored): candidate
  summary, window dates, minimum duration, weights, thresholds, ntfy
  topic, Adzuna `app_id`/`app_key` (free account). A `config/profile.example.yaml` with placeholder values is
  versioned.
- `data/intern-radar.db` — SQLite, gitignored.

## 10. Testing

pytest, test-driven.

- Source plugins: recorded JSON fixtures of real responses; no network in
  tests.
- `prefilter` and `ranking`: pure unit tests including the traps
  (Internal, International, PhD, France, date edge cases).
- `scorer`: fake `LLMBackend`; prompt building, schema parsing, partial
  answers, failures → `pending`.
- `store`: in-memory SQLite.
- `notifier`: fake HTTP transport; message formatting.
- `pipeline`: end-to-end with fake sources, backend and notifier.
- `check-sources` is the manual integration test against real APIs.

CI: GitHub Actions running ruff and pytest on every PR.

## 11. Deployment

- Repo cloned in `/root/remote-claude/intern-radar`, `poetry install`.
- `config/profile.yaml` created from the example.
- crontab:
  - `0 8-22/2 * * *  flock -n /tmp/intern-radar.lock poetry run intern-radar run`
  - `0 21 * * *      poetry run intern-radar digest`
- The crontab sets `PATH` to include `~/.local/bin` so that `poetry`
  and `claude` resolve; `claude` uses the existing logged-in session.
- logrotate rule for `logs/`.

## 12. Repository and milestones

Public repo `rmouahid/intern-radar`, Git Flow (`main`, `develop`,
`feature/*`), Conventional Commits.

1. Skeleton: models, config, store, CLI, CI.
2. Greenhouse, Lever, Ashby, Workable, SmartRecruiters plugins + pre-filter.
3. Scorer (`claude -p`) + ranking.
4. ntfy notifier, `digest` and `list` commands.
5. Workday, custom portals, Adzuna plugins + `check-sources`.
6. Full, verified `companies.yaml` + cron deployment.
