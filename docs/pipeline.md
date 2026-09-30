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
| `intern-radar-dashboard` | simple, `Restart=always` | `intern-radar dashboard` | always on, Tailscale address only |

All outbound except the dashboard, which listens on the Tailscale address
only (never on a public interface). External dependencies: public job
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
         └─ passes ─► pending ─┬─ group already scored ─► scored (inherited, same dates)
                               ├─ LLM answer ─► scored ─┬─ score NULL  → excluded, never sent
                               │                        ├─ ≥ 7.5       → notified_at
                               │                        └─ 5.5–7.5     → digested_at
                               └─ 3 answers without it ─► stays pending, no longer retried
```

Measured on the first day: 935 rows, 5.3 MB (descriptions of pending jobs
are the bulk). Growth follows new postings (~30/day), i.e. well under
1 MB/week.

## 3. Stages

### 3.1 Collection (`intern_radar/sources/`)

116 companies in `config/companies.yaml` (tiers: 8 S, 50 A, 58 B, plus the
Adzuna catch-all). 82 have a live feed, 34 have none and rely on Adzuna
(list widened on 2026-09-30 with AI labs and startups, AI infrastructure,
quant firms, fintechs and hardware groups, each board probed first).

Adzuna is targeted at those companies: each fetch asks, per country (12),
for `what=intern` offers of the last 14 days mentioning the names and aliases
of the companies with `source: none` (`what_or`, generic words such as "ai"
or "group" removed), then keeps only the offers whose employer matches a
watched company. The previous generic search returned 200 offers per fetch
from employers outside the watch list and none from Google, Meta, Apple…;
the targeted one returned 91 offers, all from watched companies (Siemens,
IBM, ByteDance, BCG, Meta, Google, Sea, Grab, JPMorgan…), 77 of them passing
the pre-filter. The API's `company` filter was rejected: it needs Adzuna's
canonical employer name (`Meta` → HTTP 400, `Apple` → 0 results).

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
- Location: rejected only when every place listed is French. Places are
  separated by `; | / & and or`; inside a place, commas separate city,
  region and country. A place naming France through its country
  (*France*, ISO `FR`/`FRA`) or a French region is French whatever its city
  (`Clichy, Ile-de-France, FRA`). Without such a marker each comma part
  counts on its own (`Paris, London` passes); neutral parts such as
  *Remote*, *EU*, *Île-de-France* are ignored; "excluding France" is not
  French.
- Field: titles clearly outside AI/ML, data, software or research are
  rejected before scoring (`is_out_of_scope`): finance, accounting, audit,
  tax, HR, recruiting, marketing, sales, communication, media, legal,
  compliance, public policy, procurement, supply chain, logistics,
  operations, quality, UX… (whole words, plus `extra_excluded_title_words`).
  Any in-scope word (AI, ML, data, software, research, science, NLP,
  vision, robotics, quant, analytics, GPU…) keeps the title, and titles
  naming no field (*Intern 2027*) go to the LLM. Team names that appear in
  every title of a company (*Amazon University Talent Acquisition*) and
  technical fields (manufacturing) are deliberately not excluded.
  Replayed on the production database: 363 of 1,162 scored offers (31 %)
  would have been rejected, 43 % of those with an AI relevance ≤ 3, and
  none of the offers ever notified or digested. Counted as
  `out_of_scope=N` in the run summary.
- Offer age: an offer first published more than `max_offer_age_days` (60)
  ago is rejected at collection, before any LLM call (`stale=N` in the run
  summary), and stored offers older than that are no longer due for
  immediate notifications or the digest. Offers without a date are kept;
  `0` disables the rule. Measured on 2026-09-30: 220 of 1,179 scored offers
  were older than 60 days (up to 487 days), 34 of them had been sent; they
  are usually filled or evergreen postings.
- Recruiting cycle: a title whose years are all before the window start
  year (`2026 SDE Intern`, `Fall 2026`) is rejected; `2026-2027`,
  `Summer 2027`, `Class of 2029` and titles without a year are kept.
  Replayed: 47 scored offers, 4 of them notified or digested.
- Degree level: titles naming only bachelor's / undergraduate students
  (`Intern, Bachelor’s`, `Undergrad Intern`) are rejected unless they also
  name master's, graduate, MS or PhD students; descriptions stating it are
  handled by the LLM (`undergrad_only`, §3.3).
- Adzuna offers whose company and title match an ATS offer are stored as
  `duplicate`.

### 3.2b Posting groups (`grouping.py`, pure)

Large companies publish one internship per country (*SDE Intern - Germany*,
*SDE Intern - UK*). `group_key(company, title)` lower-cases the title, strips
trailing place suffixes (`- Germany`, `, Singapore`, `(Remote)`, from a list
of ~70 countries and regions) and punctuation; it is stored in
`jobs.group_key` (indexed, back-filled on first open of an older database).

- Scoring: `Store.pending()` returns one job per group; after each run, and
  before selecting a batch, `inherit_group_assessments()` copies the scored
  member's assessment, score, `notified_at` and `digested_at` to the pending
  members. A country added later is therefore never announced again.
- Notifications: members due together are sent as one message whose
  location line lists up to 5 distinct places, each linked to its own offer
  when the URLs differ (`+N` beyond). The digest shows one entry per group.
- Measured on the production database: 1,162 scored jobs form 972 groups,
  i.e. **190 LLM assessments (16 %) avoidable**.
- Not grouped: different companies, reworded titles.

### 3.3 LLM scoring (`scorer.py`)

- Backend: `claude -p --model haiku --output-format json --json-schema …
  --tools "" --no-session-persistence --strict-mcp-config`. No tools and no
  MCP servers: a prompt injection in a posting can only change the answer,
  never execute anything.
- Batches of 10 jobs; descriptions cleaned (§3.3b) then truncated to 3,000
  characters; jobs are numbered 1..n in the prompt (long source ids were
  mangled by the model).
- Eligibility enum: `ok`, `phd_only`, `undergrad_only`,
  `local_students_only`, `unknown`. `undergrad_only` is defined for a
  master's-level candidate: only bachelor's students named, or master's
  explicitly excluded ("Bachelor's or Master's" and silence do not count).
  Checked on 20 stored offers: 10/10 bachelor-only postings classified
  `undergrad_only` (one via a Portuguese *bacharelado* requirement), no
  master's-level posting misclassified.
- Work authorisation enum (French citizen, this location): `free` (EU/EEA/
  Switzerland), `self_arranged` (a country where the candidate obtains the
  visa without an employer sponsor, e.g. a working holiday visa;
  `self_sponsored_countries`), `programme` (standard intern visa: US J-1, UK GAE, Working
  Holiday…), `sponsorship_stated`, `uncertain`, `unlikely`; `visa_note`
  keeps the explanation. Assessments stored before the field existed load
  as `uncertain`. Checked on 10 stored offers from 10 countries: EU → free,
  US → programme, UK → uncertain, China/Korea → unlikely.
- Every item is validated (types, enums, 0–10 range); invalid or missing
  items stay `pending` and count an attempt; after 3 attempts the job is no
  longer retried.
- A CLI failure (non-zero exit, `is_error`, invalid JSON, timeout 600 s)
  raises `LLMError`: the whole run stops scoring, **no attempt is counted**,
  jobs are retried next run. The error message carries the envelope's
  `api_error_status`, `subtype` and `result`.
- Caps per run: `max_llm_batches_per_run` (5) × 10 jobs. The backlog is
  ordered tier S → A → B → unlisted, newest first.

### 3.3b Description cleanup (`description.py`, pure)

Descriptions often open with the company presentation and end with
benefits, pay and legal notices, so the 3,000-character scoring window
missed the responsibilities, requirements and dates. `clean_description()`
is applied to every LLM prompt (scoring and letter draft); the stored text
is unchanged, and the letter fact check still uses the raw text.

- Short heading lines (≤ 70 characters, emoji and trailing `:`/`?`
  ignored) open a section. *Company description, About us / About <name>,
  Who we are, Benefits, Perks, What we offer, What's in it for you, Pay
  range, Salary, EEO, Accommodations, Privacy, Disclaimer, How to apply…*
  are dropped until the next role heading (*Job description, The role,
  Responsibilities, What you'll do, Requirements, Qualifications, About the
  role…*). Unknown headings never end a section; anything unrecognised is
  kept.
- Legal lines are dropped wherever they appear (equal opportunity,
  accommodation, applicant privacy, pay range, E-Verify…), plus the opening
  paragraph Amazon repeats on every posting. Lines mentioning a duration or
  period (*12 weeks*, *summer*, *start date*, month names) are kept even
  inside a dropped section; sections about the team or the programme
  (*About the team*, *About the X Internship*) belong to the role.
- Blank and repeated lines are collapsed; an empty result falls back to the
  original text.
- Measured on the 1,083 stored descriptions: average length 4,835 → 3,637
  characters (−25 %), offers above the 3,000-character window 845 → 660.
- Quality check (30 stored offers, 12 of them notified or digested, scored
  again with raw and with cleaned text): agreement with the stored
  assessment is equal or better with cleaned text — internship 30/30 vs
  30/30, dates 25 vs 24, eligibility 22 vs 17, relevance within ±1 21 vs 21.

### 3.4 Ranking (`ranking.py`, pure)

```
excluded (score NULL) if: not an internship, dates incompatible, PhD only,
                          undergraduate only,
                          language other than EN/ES/FR, AI relevance < 6
score = 0.3·tier + 0.5·relevance + 0.2·dates      (tier S10 A8 B6 unlisted4;
                                                   dates fits10 unknown6 short4)
      − 2 if local students only                   rounded to 0.1
      − visa penalty: free 0, self_arranged 0, programme 0.5, sponsorship_stated 0,
                      uncertain 1, unlikely 3      (never excludes)
```

Thresholds: ≥ 7.5 immediate, 5.5–7.5 digest (both configurable).

Weights were 0.5/0.3/0.2 until 2026-09-30: company tier dominated, so a
tier-B offer with unknown dates capped at 7.2 and could never be notified
(Snowflake *Software Engineer Intern (AI / ML)*, relevance 9 → 6.9), while a
tier-S offer passed with a middling relevance. Replaying the stored
assessments since the initial backlog: same number of immediate offers (2),
but the undergraduate-only Amazon programme is replaced by the Snowflake one.

`intern-radar rescore` recomputes every stored score from its stored
assessment after a change of weights, penalties or `min_relevance` (no LLM
call). Offers already notified or already sent in a digest are never sent
again as immediate offers.

### 3.5 Notifications (`notifier.py`, `telegram.py`)

- HTML messages (only `<b>`, `<i>`, `<a>`; every dynamic value
  `html.escape`d, including `href`), link previews off.
- Offer: company, title, location, score, dates, work-authorisation label
  (bold) and visa note, summary (fields
  capped: 80/200/100/300/500 characters), buttons *Voir l'offre* (only for
  `http(s)` URLs) and *Lettre de motivation* (`callback_data = L:<rowid>`,
  within Telegram's 64-byte limit).
- Posting groups: one message per group, locations joined (§3.2b).
- Digest: ≤ 15 groups (keeps the rendered text under 4,096), silent. When
  letters are configured (the listener runs), entries are numbered and an
  inline keyboard of `🔔 1` … `🔔 15` buttons (5 per row, `callback_data =
  P:<rowid>` of the group lead) is attached.
- Work authorisation fixed by rules (`countries.py`, `ranking.with_rule_based_visa`):
  offers in the EU/EEA/Switzerland are always `free` and offers in a
  `self_sponsored_countries` location are `self_arranged`, whatever the LLM
  said; countries are recognised by name, ISO-3 code (upper case) and main
  cities, never by two-letter codes (`CA` is California as often as
  Canada). Applied at scoring and by `rescore`, which also fixes
  assessments stored before the field existed.
- Interview chance (`chance.py`): when `config/candidate.json` exists,
  every immediate or promoted notification ends with
  `🎯 Chance d'entretien : N %` and 1–3 reasons (✅ / ⚠️, French, ≤ 15
  words). One LLM call per offer (`chance_model` sonnet, `chance_effort`
  low) at notification time, never during bulk scoring. Recalibrated on
  2026-09-30 (the first version anchored every company on "a few percent"):
  explicit base rates by company type (elite quant 2–5 %, big tech mass
  programmes 5–10 %, frontier AI labs 5–15 %, scale-ups 10–25 %, startups
  and mid-size European companies 20–40 %), a fit multiplier (×0.5 to ×2,
  judged on this candidate's profile), bounded adjustments (−30 % to +20 %
  each) for work authorisation, eligibility, language and offer age, and an
  instruction to use the whole scale. A `self_arranged` or `free` work
  authorisation counts as a strength. `rescore` clears stored estimates so
  they are recomputed with the current method. Stored in the `chances` table and reused on re-send; a failure
  only omits the line. Measured: ~$0.025–0.04 API-equivalent and 4–6 s per
  estimate (e.g. NVIDIA *Deep Learning*, Santa Clara: 3 %). It is an
  estimate until application outcomes (#42) allow calibration.
- Promotion (`promotion.py`): the listener routes `P:` taps to `Promoter`,
  which sends the offer and its posting group exactly as an immediate
  notification (with *Voir l'offre* and *Lettre de motivation*) and marks
  every member `notified_at`. Tapping again re-sends it; unknown or
  unscored refs are answered "Offre introuvable".
- Alerts (silent): a source failing for 3 consecutive days, the LLM failing
  for 1 day; each alerted once per streak.
- Delivery semantics: an offer is marked `notified_at` only after Telegram
  answers `ok`. Transient failures (network, 429 after one retry, 5xx) stop
  the notification step and everything is retried next run. Permanent
  rejections (4xx other than 429) are logged, marked and skipped so that one
  bad message cannot block later ones. At most `max_immediate_per_run` (10)
  posting groups per run.

### 3.6 Cover letters (`letters/`)

Triggered by a button tap:

1. `getUpdates` long poll (50 s, read timeout 60 s, `allowed_updates =
   ["callback_query"]`), offset persisted in `meta`; backoff 5 s → 300 s on
   errors, reset after any successful poll.
2. A tap is accepted only if both the chat id and the sender id equal
   `telegram_chat_id`; it is answered at once ("⏳ Lettre en préparation…").
3. Stored letter present → re-sent, no LLM call. Daily cap
   (`max_letters_per_day`, 10) → one notice per day.
4. Candidate facts. When `config/candidate.json` exists (see
   `generate-profile`), `select_items()` ranks experiences and projects by
   the number of their skills and keywords found (whole words) in the offer
   title and cleaned description, and the draft receives the summary,
   education, the **4 best items in full**, the others as one line, skills,
   languages and extras. The keyword report and the fidelity check use the
   **whole** profile, so a keyword present in a non-selected item is not
   reported as missing. Otherwise the CV text comes from the Google Doc PDF
   export (`pypdf`, wrapped lines rejoined), cached 24 h; a stale cache is
   used when the download fails. Measured on the NVIDIA *Deep Learning*
   offer with the first generated profile (5 items): draft prompt 2,289 →
   2,139 tokens; with a longer dossier the prompt stays bounded by the
   4-item selection.
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

### 3.7 Tailored CVs (`resume/`)

Available once `config/candidate.json` and `contact` exist: immediate and
promoted notifications get a *📄 CV adapté* button (`callback_data =
C:<rowid>`), handled by the listener.

1. Stored CV present → re-sent, no LLM call; daily cap
   `max_resumes_per_day` (10).
2. One LLM call (`resume_model` sonnet, `resume_effort` low) returns
   **content only**: headline, summary, up to 5 items by id with 2–4
   reworded bullets (≤ 25 words), skill groups.
3. Fact check in Python: unknown item ids are ignored; a bullet containing a
   proper noun or number absent from its own item is dropped (an item left
   empty falls back to its recorded actions); skills are restricted to the
   profile's skills; an unsupported headline is removed and an unsupported
   summary replaced by the profile summary.
4. Layout (`fpdf2`, A4, Helvetica, left-aligned real text for ATS):
   header, headline, summary, education (copied from the profile),
   experience, projects, skills, languages. **Exactly one page**: the font
   shrinks (10 → 9 pt), then the last bullets, then the last items are
   removed; the caption reports what was dropped.
5. Delivery: `data/cvs/<hash>/<Name>_CV_<Company>_<Title>.pdf` as a Telegram
   document with a caption (items shown, bullets dropped by the fact check
   or to fit).

Measured on the NVIDIA *Deep Learning* offer with the production profile:
8–9 s, one page, no bullet dropped.

### 3.8 Application tracking (`tracking.py`)

When the listener runs, immediate and promoted notifications carry a second
row: *✅ Postulé* (`A:<rowid>`) and *🙈 Pas intéressé* (`D:`). The state
machine is pure and tested:

```
(new) ─✅→ applied ─🗣→ interview ─🎉→ offer
  │          │ └─❌→ rejected      └─❌→ rejected
  │          └─🔕→ no_answer ─🗣/❌→ interview / rejected
  └─🙈→ dismissed ─✅→ applied
```

- A tap stores the new status (`applications` table: status, last update,
  first application date, reminder date), answers with the new status and
  replaces the tracking row of the tapped message with the next steps
  (`editMessageReplyMarkup`; the other buttons are kept). An invalid step is
  answered "Déjà : …" and changes nothing; a keyboard update failure never
  loses the status.
- A dismissed posting is never announced again for another country: the
  posting group already carries its notification date (§3.2b).
- Reminders: the evening `digest` run sends one *⏰ Relance* per application
  still `applied` after `reminder_days` (14), with *Entretien / Refusé /
  Pas de réponse* buttons, then marks it reminded.
- `intern-radar applications` lists the tracker (status, last update,
  application date, link).

### 3.9 Dashboard (`dashboard/`)

`intern-radar dashboard` serves one page at
`http://<tailscale-ip>:8787/` (`dashboard_host`, `dashboard_port`; the host
defaults to `tailscale ip -4` and the command refuses to start without it).
Standard library HTTP server, server-rendered HTML, inline SVG charts, no
JavaScript, no new dependency; the SQLite file is opened read-only per
request (`mode=ro`), so the page can never change data. `/healthz` answers
`ok`.

**Pipeline** section: state of `intern-radar-run.service` (running since…,
or last result, end time and summary line) and a *Lancer un run* button.
`POST /run` asks systemd to start that unit (`systemctl start --no-block`),
exactly as the timer does, so a manual run gets the same environment, logs
and timeout, and systemd never starts a second instance while one is active
(the button is disabled and the page reloads every 15 s during a run). The
request is accepted only when its `Origin` (or `Referer`) is the dashboard
itself; otherwise it gets HTTP 403. The data stays read-only.

Sections: key figures (offers seen, scored, immediate, digest, applications,
interviews, offers, LLM cost over 7 days), weekly funnel by cohort (seen →
pre-filter → scored → sent → applied → interview) with a bar chart, score
histogram with the digest and immediate thresholds, applications, sources
(offers per company, last new offer, current failure streak) and LLM usage
per day and purpose.

LLM usage comes from a new `llm_usage` table: `ClaudeCliBackend(on_usage=…)`
records model, input tokens (fresh + cache), output tokens, API-equivalent
cost and duration of every successful call, tagged `scoring`, `letter`,
`chance` or `cv`.

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

- 34 watched companies (Google, Meta, Apple, Mistral, Goldman, Citadel…)
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
- Adzuna free tier: `min_interval_hours: 6` in `companies.yaml` limits it to
  about 3 fetches a day (12 requests each, ~36/day). The interval is a
  generic company parameter: the last successful fetch time is kept in
  `meta` (`last_fetch:<company>`).

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
  batch). `--effort low` has no effect on haiku; `MAX_THINKING_TOKENS` in
  the CLI environment does. Measured on 2026-09-30 (50 stored offers, 15 of
  them notified or digested, 3 runs per mode; the capped mode ran later on
  a partly different sample, 24 offers in common):

  | Mode | Output / batch (reasoning) | API-equiv. / batch | Latency | Final band agreement, run-to-run | vs default |
  |---|---|---|---|---|---|
  | default | 8,861 (7,251) | $0.053 | 91 s | 0.78–0.89 | — |
  | `MAX_THINKING_TOKENS=2048` | 5,488 (3,849) | $0.040 | 57 s | 0.65 | 0.63 |
  | `MAX_THINKING_TOKENS=0` | 1,672 (0) | $0.017 | 20 s | 0.83 | 0.79 (0.60 on the common 24) |

  Without reasoning, `dates_fit` drifts to `fits` (agreement with the
  default 0.53 vs 0.73 run-to-run): 12-week summer internships and 12-month
  placements are judged compatible with a March–August window, giving 9
  immediate offers instead of 5 on the sample. The 2,048 cap saves 23 %
  and makes decisions less stable. **Decision: keep the default
  reasoning**; the cost is instead reduced upstream (rule-based filters,
  posting groups, description cleanup).
- Descriptions are cleaned of boilerplate (−25 % on average, §3.3b), then
  truncated at 3,000 characters for scoring and 6,000 for letters; lowering
  the limits reduces input linearly.
- A second tap on the same offer costs nothing (stored letter).
- Cost per notified offer depends on the pass rate: with the current
  filters about 7 offers per 100 scored reached the immediate band.

## 8. Operations

```bash
systemctl list-timers 'intern-radar*'
systemctl status intern-radar-letters
journalctl -u intern-radar-run -n 50            # last run: fetched=… scored=… errors=… grouped=…
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

- 216 tests (`pytest`), offline: source plugins run against payloads that
  mirror the real API responses (captured on 2026-09-24); LLM, Telegram and
  SMTP are replaced by fakes; SQLite runs in memory.
- `ruff check` + `ruff format --check` in GitHub Actions on every PR.
- Every feature went through a written spec, a plan, test-first
  implementation and an independent whole-branch review; review findings
  were fixed with a failing test first (specs and plans in
  `docs/superpowers/`).
- Manual end-to-end checks against real services before each merge (job
  boards, LLM, Telegram, PDF read back with `pypdf`).
