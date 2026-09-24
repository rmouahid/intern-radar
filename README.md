# intern-radar

[![Tests](https://github.com/rmouahid/intern-radar/actions/workflows/tests.yml/badge.svg)](https://github.com/rmouahid/intern-radar/actions/workflows/tests.yml)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**An internship radar for AI roles.** intern-radar watches the career
pages of 66 top AI/tech companies and large groups with strong AI teams,
triages every new internship with an LLM against a candidate profile, pushes
the relevant ones to Telegram, and writes a tailored, fact-checked cover
letter as a PDF on demand from the notification itself.

- **9 source adapters** (Greenhouse, Lever, Ashby, Workable, SmartRecruiters,
  Workday, Amazon, Microsoft, Adzuna), polite by design (≥ 1 s per host).
- **Rules first, LLM second**: a pure pre-filter removes noise for free; the
  LLM returns a strict JSON assessment; the final score is computed in
  Python, deterministic and testable.
- **Telegram delivery** with inline buttons, a silent evening digest and
  health alerts, no inbound port on the server.
- **Cover letters in ~25 s**: one tap → draft from CV facts only, ATS keyword
  check, anti-cliché pass, fidelity check, one-page PDF in the chat.
- **Built to run unattended** on a 1 vCPU / 2 GB VPS under systemd, with
  failure isolation at every level and measured LLM costs (~$0.39/day in
  API-equivalent quota at steady state).
- **216 offline tests**, CI on every pull request.

## Why

I am looking for a 4–6 month AI engineering internship abroad in 2027, and
the offers that matter most are published on the companies' own career
pages, at different times, on a dozen different platforms. Checking them by
hand does not scale, and generic job alerts cannot judge whether an offer
fits a precise window (March–August), a profile (RAG, LLM, agents) or visa
constraints. intern-radar does that triage continuously and turns a good
offer into a ready-to-review application in one tap.

## How it works

```
 ┌─────────────┐   ┌─────────────┐   ┌──────────────┐   ┌─────────────┐   ┌───────────┐
 │  COLLECT     │ → │ PRE-FILTER  │ → │ LLM TRIAGE   │ → │ RANK        │ → │ NOTIFY    │
 │ 9 adapters   │   │ title, loc, │   │ JSON schema, │   │ tier·0.5 +  │   │ Telegram  │
 │ 66 companies │   │ duplicates  │   │ 10 per call  │   │ AI·0.3 +    │   │ + digest  │
 └─────────────┘   └─────────────┘   └──────────────┘   │ dates·0.2   │   └─────┬─────┘
   every 2 h, 08:00–22:00 Europe/Paris (systemd timers)  └─────────────┘         │
                                                                     tap "✍️ Lettre"
                                                                              ▼
          CV (Google Doc PDF) → draft + keywords → ATS edits → anti-cliché edits
                    → fidelity checks → one-page PDF → Telegram (+ e-mail)
```

1. **Collect** — adapters query public job-board APIs, keep internship
   titles only and skip postings already seen; one broken posting or source
   never stops the run.
2. **Pre-filter** — whole-word internship regex, France-only locations
   dropped, Adzuna copies of ATS postings marked as duplicates.
3. **LLM triage** — a headless LLM CLI (`claude -p`, no tools) returns, per
   offer, internship status, AI relevance, fit with the internship window,
   eligibility, visa note, language requirement and a summary, validated
   against a JSON schema.
4. **Rank** — `0.5 × company tier + 0.3 × AI relevance + 0.2 × dates`,
   with hard exclusions (PhD only, incompatible dates, non-AI roles…).
5. **Notify** — score ≥ 7.5: Telegram message with *Voir l'offre* and
   *Lettre de motivation* buttons; 5.5–7.5: evening digest; alerts when a
   source or the LLM fails for too long.
6. **Write the letter on demand** — see
   [Cover letters](docs/pipeline.md#36-cover-letters-letters).

An offer notification:

```
🔥 Amazon · niveau S
2027 Software Dev Engineer Intern
━━━━━━━━━━━━━━━━
📍  Dublin, Irlande
⭐  8.0 / 10
📅  Dates compatibles
🛂  UE : pas de visa nécessaire
━━━━━━━━━━━━━━━━
Stage de développement logiciel sur les services d'Amazon…
[ 🔗 Voir l'offre ]  [ ✍️ Lettre de motivation ]
```

## Tech stack

| Concern | Choice |
|---|---|
| Language, packaging | Python 3.12+, Poetry |
| HTTP | httpx (shared client, per-host throttle, 20 s timeout) |
| Storage | SQLite (single file, short transactions) |
| LLM | headless LLM CLI with JSON-schema output (haiku for triage, sonnet for letters) |
| Messaging | Telegram Bot API (HTML messages, inline buttons, long polling) |
| Documents | fpdf2 (PDF rendering), pypdf (CV text extraction) |
| CLI | Typer |
| Scheduling | systemd timers and services, logrotate |
| Quality | pytest, ruff, GitHub Actions |

## Quick start

Requirements: Python ≥ 3.12, [Poetry](https://python-poetry.org), the
`claude` CLI logged in, a Telegram account.

```bash
git clone https://github.com/rmouahid/intern-radar.git && cd intern-radar
poetry install
cp config/profile.example.yaml config/profile.yaml     # gitignored
```

1. Create a bot with [@BotFather](https://t.me/BotFather) (`/newbot`), send
   it `/start`, then set `telegram_token` and `telegram_chat_id`
   (read `chat.id` from `https://api.telegram.org/bot<token>/getUpdates`).
2. Describe the candidate (`candidate_summary`, `window_start`,
   `window_end`, `min_months`).
3. Optional: `adzuna_app_id` / `adzuna_app_key` (free), and for cover
   letters `cv_url`, `contact`, `letters_email`, `smtp_app_password`.

```bash
poetry run intern-radar check-sources      # which feeds answer
poetry run intern-radar run --dry-run      # full pass, prints instead of sending
```

Every setting is described in [docs/configuration.md](docs/configuration.md).

## Usage

```bash
poetry run intern-radar run                  # collect, triage, notify
poetry run intern-radar digest               # evening digest
poetry run intern-radar list --min-score 6   # stored offers, best first
poetry run intern-radar letter <job_id>      # write (or re-send) one letter
poetry run intern-radar listen               # wait for letter button taps
```

## Deployment

```bash
ln -sf "$PWD"/deploy/intern-radar-*.service "$PWD"/deploy/intern-radar-*.timer /etc/systemd/system/
cp deploy/logrotate.conf /etc/logrotate.d/intern-radar
systemctl daemon-reload
systemctl enable --now intern-radar-run.timer intern-radar-digest.timer
systemctl enable --now intern-radar-letters.service
```

Runs every 2 hours from 08:00 to 22:00 and sends the digest at 21:00,
Europe/Paris time (DST handled by systemd). The unit files assume the
repository lives in `/root/remote-claude/intern-radar`. Operations and
runbook: [docs/pipeline.md §8](docs/pipeline.md#8-operations).

## Measured results

From the production VPS (details in
[docs/pipeline.md §7](docs/pipeline.md#7-llm-usage-and-cost-measured)):

| Metric | Value |
|---|---|
| Internship postings found on the first run | 928 across 44 live feeds |
| Steady-state run | ~2 min collection + up to 5 LLM batches, ~9 min total |
| Triage | 10 offers per LLM call, 80–110 s, $0.072 API-equivalent |
| Cover letter | 3 LLM calls, 25 s, $0.084 API-equivalent (down from 56 s / $0.141) |
| Steady-state LLM usage | ~$0.39/day API-equivalent (subscription quota) |

## Project structure

```
intern_radar/
├── cli.py            Typer commands and wiring
├── config.py         profile.yaml / companies.yaml loading and validation
├── models.py         Company, Job, Assessment, ScoredJob
├── http.py           shared httpx client with per-host throttle
├── sources/          one adapter per job board + registry
├── prefilter.py      rule-based filter (pure)
├── scorer.py         LLM backend (CLI) and batched assessment
├── ranking.py        deterministic final score (pure)
├── store.py          SQLite persistence and health state
├── pipeline.py       one run: collect → filter → score → notify → alert
├── notifier.py       HTML message formats, Telegram notifier
├── telegram.py       minimal Bot API client
└── letters/          CV source, writer, checks, PDF, delivery, listener
config/               companies.yaml (versioned), profile.example.yaml
deploy/               systemd units, logrotate
tests/                216 offline tests mirroring the package layout
docs/                 technical documentation
```

## Engineering practices

- **Test-driven**: every behaviour starts as a failing test; source adapters
  are tested against payloads mirroring the real API responses; the LLM,
  Telegram and SMTP are faked, so the suite runs offline in under a second.
- **Design before code**: each feature has a written design and an
  implementation plan (`docs/superpowers/`), then an independent review of
  the whole branch before merging.
- **Measured, not assumed**: costs, latencies and failure behaviour are
  checked against the real services; the numbers above come from logs and
  LLM usage envelopes.
- **Git Flow, Conventional Commits, linear history** (rebase merges), CI
  (ruff + pytest) on every pull request.

## Limitations

19 watched companies (Google, Meta, Apple, Mistral…) publish no usable feed
and are only reachable through Adzuna. The LLM triage is a filter, not a
verdict: repeated scoring of the same offers disagrees on about 3 in 10
categorical judgements, and ~40 % of postings do not state their dates.
The full list is in [docs/pipeline.md §6](docs/pipeline.md#6-limits-and-known-gaps).

## Documentation

| Document | Content |
|---|---|
| [docs/architecture.md](docs/architecture.md) | context, components, design decisions and their trade-offs |
| [docs/pipeline.md](docs/pipeline.md) | stage-by-stage reference, failure modes, limits, LLM costs, operations |
| [docs/configuration.md](docs/configuration.md) | every profile and company setting |
| [docs/development.md](docs/development.md) | setup, conventions, testing, adding a source |

## Author

**Rayân Mouahid** — computer engineering student at CY Tech, working on
RAG, LLM agents and data engineering.
[GitHub](https://github.com/rmouahid) ·
[LinkedIn](https://www.linkedin.com/in/rmouahid)

## License

[MIT](LICENSE)
