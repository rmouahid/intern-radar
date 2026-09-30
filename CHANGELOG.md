# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

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

[0.2.0]: https://github.com/rmouahid/intern-radar/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/rmouahid/intern-radar/releases/tag/v0.1.0
