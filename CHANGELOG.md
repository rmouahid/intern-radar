# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.5.0] — 2026-10-05

### Added

- **Standard answers bank** (`/answers`): the usual application-form
  answers, pre-filled from the profiles and validated by the candidate;
  answers that depend on the offer (work authorisation, sponsorship,
  relocation, dates) follow its work authorisation rules, in English or
  French (#110).
- **Application kit** on every offer page: link to the form, CV and letter
  freshness, every answer with copy buttons, and a fact-checked "why this
  company" draft written on the background worker (#111).
- **Submission snapshots**: "J'ai postulé" sets the status to applied and
  archives the answers, the text and frozen copies of the PDFs, shown on
  the offer page and the board and exported in the CSV (#112).
- **Safari form filling**: a userscript for the *Userscripts* extension (or
  Tampermonkey) fills Greenhouse, Lever and Ashby forms in the candidate's
  own browser from the kit JSON API. It handles text, selects, checkbox and
  radio groups, and answers company-specific questions with one LLM call
  among the given options. Consents and demographic questions are never
  answered. Greenhouse dropdowns, which ignore scripted input, are listed
  with the value to pick. The script never submits and never touches
  captchas (#116, #117, #120).

### Fixed

- Transient source errors (429, 502–504) are retried with a backoff
  honouring `Retry-After`; one failing Adzuna country no longer fails the
  whole source; Wayve moved from Greenhouse to Ashby (#122).

## [0.4.0] — 2026-10-02

### Added

- **Web app** replacing the statistics page, mobile-first and served on the
  Tailscale address only: navigation bar, filterable offers list (score,
  tier, region, work authorisation, status, age, text) with one card per
  posting, and an offer page with score breakdown, chance, other
  locations, country conventions, application history and documents
  (#79, #80).
- **Actions from the web**: application status changes, letter and CV
  generation and Telegram delivery on a background worker (#81); hand
  edits of letters and CVs re-rendered as PDF (#83).
- **👍/👎 feedback** on offers, summarised into the scoring prompt to
  calibrate AI relevance (#82).
- **Applications board** with follow-up fields (contact, deadline,
  interviews, next action, notes), agenda and CSV export (#84, #92).
- **Skills gap** page: skills requested by relevant offers that the profile
  does not show, without any LLM call (#85).
- **Saved searches** with Telegram alerts on new matching offers (#86).
- **Profile page**: view `candidate.json`, edit `career.md`, regenerate the
  profile in the background with warnings and diff (#87).
- **Company pages** with offers seen per week, open offers, applications
  and source health (#88).
- **Run history** with per-step timings and failing sources, and **chance
  calibration** against real outcomes on the stats page (#89, #90).
- **Installable app**: manifest, icons and an offline-reading service
  worker (active over HTTPS) (#91).

### Changed

- Runs fetch sources and score batches concurrently and skip detail
  requests for offers the pre-filter rejects (#77).

### Fixed

- Concurrent scoring crashed when recording LLM usage from worker threads
  (#93).

## [0.3.0] — 2026-10-01

### Added

- **Country conventions for tailored CVs and cover letters**, from the
  candidate's writing guide: the region of the offer sets the paper (Letter
  or A4), page limit, spelling, date style, section order and titles, the
  tabular German-style CV, the right-to-work line, local mentions
  (referees, GDPR clause), and the letter's salutation, closing, date,
  subject line and length; letters follow a hook / proof / fit / closing
  structure (#70, #72).
- **Discovery offers**: AI internships from employers outside the watch
  list (EU/EEA/Switzerland or working-holiday countries), labelled
  *découverte* (#74).
- **Self-arranged work authorisation**: `self_sponsored_countries` (e.g.
  working-holiday visas) are not penalised; EU/EEA/Swiss offers are always
  visa-free by rule (#68).
- **Dashboard run button** to start a run through systemd (#66).
- Watch list widened from 65 to **116 companies**; Adzuna now targets the
  watched companies without a public feed (#60, #62).

### Changed

- Interview-chance estimates are recalibrated: explicit base rates by
  company type, fit multiplier and bounded adjustments (#68).
- Offers first published more than 60 days ago are dropped and never sent
  (`max_offer_age_days`) (#64).
- The candidate profile gains project links and a certifications field.

## [0.2.0] — 2026-09-30

### Added

- **Candidate profile**: a long-form career dossier (`config/career.md`,
  optional PDF/DOCX attachments through the `documents` extra) is turned
  into a structured profile by `intern-radar generate-profile`, with stable
  ids, skills citing their evidence and warnings for unsupported facts
  (#38).
- **Tailored CVs**: a *📄 CV adapté* button produces a one-page PDF CV for the
  offer, every bullet traced back to the profile (#41).
- **Interview chance**: immediate and promoted notifications show the
  estimated chance of reaching a first interview with its reasons (#40).
- **Application tracking** from Telegram (applied, interview, offer,
  rejected, no answer, dismissed), reminders after 14 days and
  `intern-radar applications` (#42).
- **Digest promotion**: numbered `🔔 n` buttons turn an evening-digest offer
  into a full notification (#37).
- **Dashboard** served on the Tailscale address only: funnel, score
  histogram, sources health, applications and LLM usage (#43).
- **LLM usage recording**: tokens, cost and duration of every call (#43).
- `intern-radar rescore` recomputes stored scores after a settings change
  (#35).
- Work-authorisation feasibility in the assessment and the score, with
  configurable `visa_penalties` (#34).

### Changed

- Default weights are now 0.3 tier / 0.5 AI relevance / 0.2 dates (#35).
- Cover letters are grounded on the structured profile when it exists, with
  the four most relevant experiences or projects (#39).
- Descriptions are stripped of boilerplate before every LLM call (#32).
- Copies of one posting in several countries are scored and notified once
  (#30).
- Out-of-scope fields, past recruiting cycles and bachelor-only titles are
  rejected before scoring (#31, #33).

### Fixed

- France-based offers written with ISO codes or regions
  (`Clichy, Ile-de-France, FRA`) are no longer notified (#29).

### Performance

- About half of the LLM scoring calls are avoided by the posting groups and
  the rule-based filters (#30, #31); descriptions sent to the LLM are 25 %
  shorter (#32). Reasoning is kept for scoring: disabling it degraded the
  dates assessment (#36).

## [0.1.0] — 2026-09-24

### Added

- Collection from Greenhouse, Lever, Ashby, Workable, SmartRecruiters,
  Workday, Amazon, Microsoft and Adzuna for 66 watched companies.
- Rule-based pre-filter, LLM triage through a headless CLI with a strict
  JSON schema, deterministic final score.
- Telegram notifications with buttons, silent evening digest and health
  alerts.
- On-demand cover letters: draft, ATS and anti-cliché passes, fidelity
  checks, one-page PDF delivered in the chat.
- systemd units, logrotate configuration and complete documentation.

[0.5.0]: https://github.com/rmouahid/intern-radar/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/rmouahid/intern-radar/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/rmouahid/intern-radar/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/rmouahid/intern-radar/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/rmouahid/intern-radar/releases/tag/v0.1.0
