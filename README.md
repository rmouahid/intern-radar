# intern-radar

[![Tests](https://github.com/rmouahid/intern-radar/actions/workflows/tests.yml/badge.svg)](https://github.com/rmouahid/intern-radar/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Watches the career pages of ~70 top AI/tech companies (and large groups with
strong AI teams) for internship offers, scores each new offer against a
candidate profile with an LLM, and pushes the relevant ones to your phone
through a Telegram bot. Built to find a 4–6 month AI internship
abroad at the most prestigious company possible.

## How it works

Full technical reference (reliability, failure modes, limits, measured
LLM token usage and cost, operations): [`docs/pipeline.md`](docs/pipeline.md).


1. **Sources** — one plugin per job feed: public ATS APIs (Greenhouse, Lever,
   Ashby, Workable, SmartRecruiters, Workday), the Amazon and Microsoft
   career portals, and [Adzuna](https://developer.adzuna.com) as a catch-all
   for companies without a public feed. Plugins only keep internship titles
   and skip offers already seen.
2. **Pre-filter** — free rules: internship title (`intern`, `co-op`,
   `placement`…, whole words only), not located only in France, never seen
   before (SQLite).
3. **LLM assessment** — new candidates are sent in batches of 10 to
   `claude -p --json-schema` (Haiku), which returns for each offer: is it an
   internship, AI relevance (0–10), fit with the internship window,
   eligibility, visa note, language requirements, one-line summary.
4. **Final score** — computed in Python, deterministic:
   `0.5 × company tier + 0.3 × AI relevance + 0.2 × dates fit`
   (tiers S=10, A=8, B=6, unlisted=4). PhD-only roles, incompatible dates,
   non-internships and offers with an AI relevance below 6/10 (finance,
   design… internships at top companies) are excluded.
5. **Notifications** (Telegram) — score ≥ 7.5: immediate message with
   "Voir l'offre" and "Lettre de motivation" buttons; 5.5–7.5: silent evening
   digest at 21:00; source broken for 3 days or LLM unavailable for a day:
   silent alert.

## Cover letters on demand

Each offer notification carries a **✍️ Lettre de motivation** button. The
`intern-radar-letters` service long-polls Telegram for button taps (outbound
connection only, no open port), accepts them from your chat only, answers
"⏳ Lettre en préparation…" and, for each request:

1. reads the CV text from its PDF export (`cv_url`, cached 24 h);
2. drafts a ~300-word, 3-paragraph letter with the LLM (`letter_model`,
   default Sonnet), using only facts from the CV;
3. **ATS check**: extracts the offer's keywords, adds the ones the CV
   supports, and lists the ones the CV lacks (never added);
4. **anti-AI rewrite**: a second pass replaces clichés and generic phrasing;
   a blacklist check triggers one more pass if needed;
5. **fidelity check**: names and numbers found neither in the CV nor in the
   offer are flagged;
6. renders a one-page PDF and sends it in the Telegram conversation with the
   check results, and optionally by e-mail (Gmail app password).

A second tap re-delivers the stored letter. At most `max_letters_per_day`
new letters are written per 24 h.

Profile keys: `cv_url`, `contact` (name, location, phone,
email, linkedin, github), `letters_email`, `smtp_app_password`,
`letter_model`, `max_letters_per_day` (see `config/profile.example.yaml`).

```bash
poetry run intern-radar letter <job_id>   # write and deliver one letter
poetry run intern-radar listen            # wait for button taps (service)
```

## Setup

Requirements: Python ≥ 3.12, [Poetry](https://python-poetry.org), the
`claude` CLI logged in (used for scoring), Telegram on your phone.

```bash
poetry install
cp config/profile.example.yaml config/profile.yaml   # gitignored
```

Edit `config/profile.yaml`:

- `candidate_summary`, `window_start`, `window_end`, `min_months`;
- `telegram_token`: create a bot with [@BotFather](https://t.me/BotFather)
  (`/newbot`) and copy its token;
- `telegram_chat_id`: send `/start` to your bot, then read `chat.id` from
  `https://api.telegram.org/bot<token>/getUpdates`. The bot only answers
  this chat;
- `adzuna_app_id` / `adzuna_app_key`: free keys from
  [developer.adzuna.com](https://developer.adzuna.com).

Watched companies live in `config/companies.yaml` (tier, source, board id,
aliases used to attribute Adzuna offers).

## Usage

```bash
poetry run intern-radar check-sources        # which companies are covered
poetry run intern-radar run --dry-run        # full pass, prints instead of notifying
poetry run intern-radar run                  # full pass with notifications
poetry run intern-radar digest               # evening digest
poetry run intern-radar list --min-score 6   # stored offers, best first
```

`--dry-run` uses a throwaway in-memory database, so it never marks real offers
as notified.

## Deployment (systemd)

The `deploy/` directory holds timers that run a pass every 2 hours from 08:00
to 22:00 and the digest at 21:00, Paris time (DST handled by systemd):

```bash
ln -sf "$PWD"/deploy/intern-radar-*.service "$PWD"/deploy/intern-radar-*.timer /etc/systemd/system/
cp deploy/logrotate.conf /etc/logrotate.d/intern-radar
systemctl daemon-reload
systemctl enable --now intern-radar-run.timer intern-radar-digest.timer
systemctl enable --now intern-radar-letters.service   # cover letters
systemctl list-timers 'intern-radar*'
journalctl -u intern-radar-run.service -n 30
```

The unit files assume the repo lives in `/root/remote-claude/intern-radar`;
adjust `WorkingDirectory` otherwise.

## Tests

```bash
poetry run pytest -q
poetry run ruff check . && poetry run ruff format --check .
```

Every source plugin is tested against payloads mirroring the real API
responses; the LLM, Telegram and SMTP are replaced by fakes, so the suite
runs offline.

## License

MIT
