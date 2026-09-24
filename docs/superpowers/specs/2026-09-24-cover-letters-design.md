# Cover letters on demand — Design

Date: 2026-09-24
Status: draft, awaiting review
Issue: #19

## 1. Goal

From an offer notification, one tap produces a tailored cover letter as a
simple PDF, delivered to the phone (ntfy attachment) and to the mailbox
(Gmail). The candidate always reviews the letter before applying; the tool
never applies on their behalf.

### Success criteria

- One tap on "✍️ Lettre de motivation" delivers a PDF within a few minutes.
- The letter is specific to the offer and uses only facts from the CV.
- The notification reports ATS keyword coverage, keywords missing from the
  CV, and how many generic/AI-sounding phrases were rewritten.
- Any proper noun or number not found in the CV or the offer is flagged.
- No inbound port is opened on the VPS.

### Out of scope

- Applying to offers, filling forms.
- Letters in formats other than a one-page PDF (plus the plain text in
  the email body).
- An "AI detector" score (unreliable); the anti-AI step is a rewrite pass.

## 2. Flow

```
Offer notification   [Voir l'offre] [✍️ Lettre de motivation]
                                          │ ntfy app: HTTP action
                                          │ POST https://ntfy.sh/<requests topic>
                                          ▼ body = job id
VPS: intern-radar-letters.service (systemd, always on)
  streams https://ntfy.sh/<requests topic>/json (outbound connection)
  1. validate: job id exists in SQLite, daily cap not reached
  2. cached letter for this job? → deliver it again, stop
  3. CV text  ← PDF export of the Google Doc (cached 24 h)
  4. WRITE     LLM (sonnet) → letter JSON
  5. ATS       LLM keyword extraction → Python coverage → LLM revision
  6. ANTI-AI   LLM rewrite → Python blacklist check (one retry)
  7. FIDELITY  Python: proper nouns and numbers not in CV/offer → flags
  8. PDF       fpdf2 → data/letters/<file>.pdf, row in SQLite
  9. DELIVER   ntfy attachment + Gmail SMTP
  failure at any step → ntfy "échec" notification with the reason
```

## 3. Components

| Module | Responsibility |
|---|---|
| `letters/requests.py` | stream the requests topic, parse messages, resume after restart (`since=<last message id>`, ntfy keeps 12 h), deduplicate |
| `letters/cv.py` | download the CV PDF from `cv_url`, extract text (pypdf), 24 h file cache |
| `letters/writer.py` | the three LLM steps (write, ATS revision, anti-AI rewrite) with JSON schemas, through the existing `LLMBackend` |
| `letters/checks.py` | pure functions: keyword coverage, blacklist scan, fidelity check |
| `letters/pdf.py` | render the letter (A4, 25 mm margins, Helvetica 11 pt) |
| `letters/delivery.py` | ntfy attachment (PUT with `Filename`), Gmail SMTP over SSL |
| `letters/service.py` | orchestrates one request end to end; `LetterReport` result |
| `store.py` | new `letters` table: job id, file path, created_at, report JSON |
| `notifier.py` | offer notification gains the second button (HTTP action) |
| `cli.py` | `intern-radar listen` (service), `intern-radar letter <job_id>` (manual) |

The LLM backend gains a `model` override so letters use `sonnet` while
scoring keeps `haiku`.

## 4. Writing and checks

### Write (LLM, sonnet)

Input: CV text (the only allowed source of facts about the candidate),
company, title, location, full description, internship window.
Output JSON: `language`, `greeting`, `paragraphs` (3), `closing`.

Rules in the prompt: English unless the offer is written in Spanish or
French; about 300 words; paragraph 1 = why this company and role, citing
one concrete element of the offer; paragraph 2 = two or three CV projects
or experiences explicitly tied to the offer's missions; paragraph 3 =
availability (6 months between March and August 2027) and a sober close.
Never invent a skill, number, employer or experience; no filler.

### ATS

1. LLM extracts 10–15 keywords from the offer and classifies each as
   `in_cv` (justified by the CV) or `not_in_cv`.
2. Python computes coverage: `in_cv` keywords present in the letter
   (case-insensitive, word boundaries).
3. If some `in_cv` keywords are missing, one LLM revision adds them where
   natural; coverage is recomputed.
4. `not_in_cv` keywords are never added; they are listed in the report.

### Anti-AI rewrite

LLM reads the letter as a sceptical recruiter and rewrites generic or
AI-sounding passages (e.g. "thrilled", "passionate about leveraging",
"fast-paced", "delve", "cutting-edge", em-dash chains, symmetrical
triplets, claims without an example) into concrete sentences, without
adding facts; it returns the rewritten letter and the number of changes.
Python then scans a blacklist of phrases; if any remains, one more
rewrite is requested; leftovers are reported.

### Fidelity

Python extracts capitalised multi-letter tokens and numbers from the final
letter; any that appears in neither the CV text, the offer (company,
title, location, description) nor the internship dates is reported as
"à vérifier".

## 5. PDF

A4, margins 25 mm, Helvetica 11 pt (core font, Latin-1). Typographic
characters are normalised before rendering (’ → ', “ ” → ", — – → -,
… → ...); other non-Latin-1 characters are dropped and reported.

```
Rayân Mouahid
Paris, France · <phone> · <email>
<linkedin> · <github>

September 24, 2026

<Company> — Hiring Team
Re: <Job title> (<location>)

<greeting>
<paragraph 1>
<paragraph 2>
<paragraph 3>

<closing>
Rayân Mouahid
```

File: `data/letters/Mouahid_CoverLetter_<Company>_<Title>.pdf` (slugified,
≤ 80 characters).

## 6. Delivery

- **ntfy**: `PUT https://ntfy.sh/<main topic>` with the PDF as body and
  headers `Filename`, `Title: ✍️ Lettre prête · <company>`, `Message:` the
  report card below, `Tags: memo`. ntfy.sh keeps attachments 3 h; the app
  downloads the file.
- **Email**: Gmail SMTP (`smtp.gmail.com:465`, SSL) with an app password;
  from and to `letters_email`; subject `Lettre — <company> · <title>`;
  body = report + plain-text letter; PDF attached.

Report card:

```
<job title>
━━━━━━━━━━━━━━━━
🎯  ATS : 12/14 mots-clés
🚫  Absents de ton CV : Java EE, AWS Lambda
🧹  Anti-IA : 5 tournures corrigées
⚠️  À vérifier : 40%          (only when flags exist)
━━━━━━━━━━━━━━━━
📎 <file name>
```

## 7. Configuration (`profile.yaml`, gitignored)

```yaml
requests_topic: <second secret topic>
cv_url: https://docs.google.com/document/d/<id>/export?format=pdf
letters_email: prorayanmouahid@gmail.com
smtp_app_password: <Gmail app password>
letter_model: sonnet
max_letters_per_day: 10
contact:
  name: Rayân Mouahid
  location: Paris, France
  phone: "+33 …"
  email: prorayanmouahid@gmail.com
  linkedin: linkedin.com/in/rmouahid
  github: github.com/rmouahid
```

The button is only added to notifications when `requests_topic` is set;
the email step is skipped (and reported) when no SMTP password is set.

## 8. Error handling and security

- Unknown job id, malformed message, daily cap reached → ignored with a
  log line (cap reached → one ntfy notice per day).
- LLM, CV download or SMTP failure → ntfy "❌ Lettre non générée ·
  <company>" with the reason; the request can be retried with another tap.
- Stream disconnects → reconnect with exponential backoff (max 5 min),
  resuming from the last processed message id.
- The requests topic is secret and distinct from the notification topic;
  only job ids present in the database are accepted, so the topic cannot
  be used to make the LLM write arbitrary text.

## 9. Testing

- `checks.py`: coverage, blacklist, fidelity — pure unit tests.
- `writer.py`: fake `LLMBackend`; prompts contain the CV and the rules;
  ATS revision only when `in_cv` keywords are missing; anti-AI retry.
- `pdf.py`: render, read back with pypdf, assert header/body/closing;
  typographic normalisation.
- `delivery.py`: fake HTTP transport (PUT headers and body), fake SMTP
  class (message fields and attachment).
- `requests.py`: parse the ntfy JSON stream lines, dedup, `since`.
- `service.py`: end to end with fakes; cached letter re-delivered; cap.
- `notifier.py`: second action present only with `requests_topic`.
- Manual: one real letter for a stored offer via `intern-radar letter`.

## 10. Deployment

`deploy/intern-radar-letters.service`: `Type=simple`,
`ExecStart=poetry run intern-radar listen`, `Restart=always`,
`RestartSec=10`, same `WorkingDirectory`/`PATH`/`HOME` as the other units.
New dependencies: `fpdf2`, `pypdf`.
