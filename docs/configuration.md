# Configuration reference

intern-radar reads two YAML files from `config/` (override with
`--config-dir`). Both are validated at start-up; an unknown key, a missing
required key or a wrong type stops the command with exit code 2 and a
message naming the key.

| File | Versioned | Content |
|---|---|---|
| `config/companies.yaml` | yes | watched companies and how to reach their feeds |
| `config/profile.yaml` | **no** (gitignored) | candidate, schedule limits, secrets |
| `config/profile.example.yaml` | yes | documented template for `profile.yaml` |

Runtime data lives in `data/` (gitignored): `intern-radar.db` (SQLite),
`cv-cache.json`, `letters/`. Logs go to `logs/intern-radar.log`.

## profile.yaml

### Candidate and schedule

| Key | Type | Default | Description |
|---|---|---|---|
| `candidate_summary` | text | **required** | profile given to the LLM for triage (skills, projects, languages, goal) |
| `window_start` | date | **required** | earliest internship start (`YYYY-MM-DD`) |
| `window_end` | date | **required** | latest internship end; must be after `window_start` |
| `min_months` | int | **required** | minimum internship duration |

### Telegram

| Key | Type | Default | Description |
|---|---|---|---|
| `telegram_token` | string | **required** | bot token from @BotFather (secret) |
| `telegram_chat_id` | int | **required** | the only chat the bot writes to and accepts taps from |

### Triage (LLM and ranking)

| Key | Type | Default | Description |
|---|---|---|---|
| `llm_model` | string | `haiku` | model passed to the LLM CLI for triage |
| `llm_effort` | string | unset | `--effort` for triage; unset keeps the CLI default |
| `max_llm_batches_per_run` | int | `5` | batches of 10 offers scored per run |
| `max_immediate_per_run` | int | `10` | immediate notifications per run |
| `weights.tier` | float | `0.5` | weight of the company tier (S=10, A=8, B=6, unlisted=4) |
| `weights.relevance` | float | `0.3` | weight of the LLM's AI relevance (0–10) |
| `weights.dates` | float | `0.2` | weight of the dates fit (fits=10, unknown=6, too short=4) |
| `thresholds.immediate` | float | `7.5` | score for an immediate notification |
| `thresholds.digest` | float | `5.5` | score for the evening digest |
| `thresholds.min_relevance` | int | `6` | offers below this AI relevance are never notified |

### Sources

| Key | Type | Default | Description |
|---|---|---|---|
| `adzuna_app_id` | string | unset | Adzuna API id (free account) |
| `adzuna_app_key` | string | unset | Adzuna API key (secret); without both keys the Adzuna source fails and alerts after 3 days |

### Cover letters

Letters are enabled (button shown, commands usable) when `cv_url` and
`contact` are set.

| Key | Type | Default | Description |
|---|---|---|---|
| `cv_url` | URL | unset | PDF export of the CV, e.g. `https://docs.google.com/document/d/<id>/export?format=pdf` |
| `contact.name` | string | — | letter header and signature |
| `contact.location` | string | — | header |
| `contact.phone` | string | — | header (quote it in YAML) |
| `contact.email` | string | — | header |
| `contact.linkedin` | string | — | header |
| `contact.github` | string | — | header |
| `letter_model` | string | `sonnet` | model for letters |
| `letter_effort` | string | `low` | `--effort` for letters (measured: −61 % output tokens) |
| `max_letters_per_day` | int | `10` | new letters per 24 h; re-sending a stored letter is free |
| `letters_email` | e-mail | unset | Gmail address that sends and receives the copy |
| `smtp_app_password` | string | unset | Gmail app password (secret); e-mail is skipped when unset |

### Example

```yaml
candidate_summary: |
  Computer engineering student (CY Tech, France). Built a RAG agent and a
  vector search engine from scratch in Python, …
window_start: 2027-03-08
window_end: 2027-08-31
min_months: 4
telegram_token: "123456:ABC-…"
telegram_chat_id: 123456789
thresholds: {immediate: 7.5, digest: 5.5, min_relevance: 6}
cv_url: https://docs.google.com/document/d/<id>/export?format=pdf
contact:
  name: Rayân Mouahid
  location: Paris, France
  phone: "+33 …"
  email: you@example.com
  linkedin: linkedin.com/in/…
  github: github.com/…
```

## companies.yaml

A list of entries. Common keys:

| Key | Required | Description |
|---|---|---|
| `name` | yes | display name, unique |
| `tier` | yes | `S`, `A`, `B` (prestige used in the score) or `unlisted` (Adzuna catch-all only) |
| `source` | yes | adapter name, or `none` when the company has no usable feed |
| `aliases` | no | other employer names used to attribute Adzuna offers (`[DeepMind, Google DeepMind]`) |

Adapter parameters:

| `source` | Parameters | Where to find them |
|---|---|---|
| `greenhouse` | `board` | `boards.greenhouse.io/<board>` |
| `lever` | `site` | `jobs.lever.co/<site>` |
| `ashby` | `org` | `jobs.ashbyhq.com/<org>` |
| `workable` | `account` | `apply.workable.com/<account>` |
| `smartrecruiters` | `company_id` | `jobs.smartrecruiters.com/<company_id>` |
| `workday` | `host`, `tenant`, `site` | `https://<host>/<site>` career site; `tenant` is the host's first label |
| `amazon`, `microsoft` | none | fixed endpoints |
| `adzuna` | `countries` (optional list) | defaults to gb, us, ca, sg, de, nl, ch, es, it, at, be, pl |

Examples:

```yaml
- {name: Anthropic, tier: S, source: greenhouse, board: anthropic}
- {name: NVIDIA, tier: S, source: workday, host: nvidia.wd5.myworkdayjobs.com,
   tenant: nvidia, site: NVIDIAExternalCareerSite}
- {name: Google, tier: S, source: none, aliases: [DeepMind, Google DeepMind]}
- {name: Adzuna, tier: unlisted, source: adzuna}
```

Validate a change against the live APIs:

```bash
poetry run intern-radar check-sources   # OK / FAIL / NONE per company, exit 1 on any FAIL
```

## Command-line options

| Command | Options |
|---|---|
| `run` | `--dry-run` (in-memory database, prints messages), `--config-dir`, `--db` |
| `digest` | `--dry-run`, `--config-dir`, `--db` |
| `list` | `--min-score N`, `--db` |
| `check-sources` | `--config-dir` |
| `letter JOB_ID` | `--config-dir`, `--db` |
| `listen` | `--config-dir`, `--db` |
