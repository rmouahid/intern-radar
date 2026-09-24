# Telegram channel — Design

Date: 2026-09-24
Status: draft, awaiting review
Issue: #21

## 1. Goal

Replace ntfy with a Telegram bot as the only channel between intern-radar
and the candidate: offer notifications, evening digest, alerts, cover
letter requests and PDF delivery.

### Why

ntfy.sh anonymous publishing is blocked for this VPS: HTTP 429 "daily
message quota reached" after about a dozen messages in a day (the quota is
per visitor/IP). The Telegram Bot API is free, has no such quota at this
volume, supports inline buttons, HTML formatting and documents, and lets the
VPS receive button taps by long polling (no inbound port).

### Success criteria

- Offer notifications, digest and alerts arrive in the bot conversation
  with the layouts approved on the phone (section 4).
- Tapping "✍️ Lettre de motivation" shows "⏳ Lettre en préparation…"
  immediately and delivers the PDF in the conversation.
- The bot ignores every chat except the configured one.
- The bot token never appears in logs, errors, SQLite or notifications.
- ntfy code and settings are removed.

### Out of scope

- Bot commands beyond ignoring `/start` (no `/list`, `/status`).
- Group chats, several users.

## 2. Architecture

```
pipeline / digest / alerts ──► TelegramNotifier.send(Message)
                                   │ sendMessage (HTML + inline keyboard)
                                   ▼
                         api.telegram.org  ◄── candidate's phone
                                   │ getUpdates (long polling, 50 s)
                                   ▼
intern-radar-letters.service: run_listener
  callback "L:<ref>" from the configured chat
    → answerCallbackQuery("⏳ Lettre en préparation…")
    → LetterService.handle(job_id)  (unchanged pipeline)
    → sendDocument(PDF, caption = report card)
```

## 3. Components

| Module | Change |
|---|---|
| `telegram.py` (new) | `TelegramClient`: `send_message`, `send_document`, `answer_callback`, `get_updates`; `TelegramError` whose message never contains the token (the token is part of the URL); one retry on HTTP 429 using `retry_after` |
| `notifier.py` | `Message(html, buttons, silent)`, `Action(label, url=None, callback=None)`; `TelegramNotifier` replaces `NtfyNotifier`; `ConsoleNotifier` kept for dry runs; formats rewritten in HTML (section 4) |
| `store.py` | `job_ref(job_id) -> int` (SQLite rowid) and `job_by_ref(ref) -> Job \| None`, because Telegram limits callback data to 64 bytes and Workday ids are longer |
| `pipeline.py` | passes the job ref to `format_immediate` when letters are enabled (`cv_url` and `contact` set) |
| `letters/service.py` | delivers through `send_document` with the card as caption; failures and cap notices through the notifier |
| `letters/delivery.py` | `NtfyAttachmentSender` removed; `GmailSender` kept |
| `letters/inbox.py` | `RequestStream` replaced by `TelegramUpdates` (getUpdates with offset); `run_listener` stores the last `update_id` and resumes after it |
| `config.py` | new required keys `telegram_token`, `telegram_chat_id`; `ntfy_topic`, `ntfy_server`, `requests_topic` removed |
| `cli.py`, README, example profile | Telegram wiring and documentation |

## 4. Message layouts (approved)

HTML parse mode; every dynamic value is HTML-escaped; link previews off.

Offer (priority: normal sound):

```
🔥 <b>Amazon · niveau S</b>
<b>2027 Software Dev Engineer Intern</b>
━━━━━━━━━━━━━━━━
📍  Dublin, Irlande
⭐  8.0 / 10
📅  Dates compatibles
🛂  <visa note>
━━━━━━━━━━━━━━━━
<i><summary></i>
[🔗 Voir l'offre] [✍️ Lettre de motivation]
```

Letter (document caption, ≤ 1024 characters; lists are cut with "…"):

```
✍️ <b>Lettre prête · NVIDIA</b>
<b><job title></b>
━━━━━━━━━━━━━━━━

🎯  <b>ATS</b> : 4/4 mots-clés

🚫  <b>Absents de ton CV</b> :
Deep Learning, CUDA, GPU, …

🔎  <b>Déduits de ton CV (à vérifier)</b> :
…                                   (only when present)

🧹  <b>Anti-IA</b> : 8 tournures corrigées

⚠️  <b>À vérifier</b> : …            (unverified, dropped chars, 2 pages)

📧  <e-mail status>

━━━━━━━━━━━━━━━━
```

Digest (silent):

```
📋 <b>Récap du soir — 3 offres</b>
━━━━━━━━━━━━━━━━

<b>Databricks</b> · niveau A
<a href="…">ML Intern</a>
📍 Amsterdam   ⭐ 7.1 / 10

<b>Shopify</b> · niveau B
…

━━━━━━━━━━━━━━━━
```

At most 15 offers (Telegram 4096-character limit), then "… et N autres (intern-radar list)".

Alerts (silent): `⚠️ <b>Source en panne : X</b>` / `⚠️ <b>Notation LLM
indisponible</b>` / `⚠️ <b>Limite de lettres atteinte</b>` with one line
of detail. Letter failure: `❌ <b>Lettre non générée · X</b>` + title and
reason.

## 5. Listener

- `getUpdates(offset=last_update_id + 1, timeout=50,
  allowed_updates=["callback_query"])`, HTTP read timeout 60 s.
- A callback is accepted only if both the message chat id and the sender
  id equal `telegram_chat_id`; others are answered with nothing and
  ignored.
- `callback_data` format: `L:<ref>`; unknown refs are answered
  "Offre introuvable".
- The callback is answered ("⏳ Lettre en préparation…") before the
  letter is written, so the phone stops its spinner.
- `last_update_id` is stored in SQLite `meta`; backoff on network errors as
  before (5 s doubling to 300 s).

## 6. Error handling and security

- `TelegramError` carries the API method and HTTP status (and Telegram's
  `description` field), never the URL.
- `httpx` request logging stays silenced (the URL contains the token).
- Notifications are marked sent only after Telegram answers `ok: true`,
  as before.
- `telegram_token` and `telegram_chat_id` live only in the gitignored
  `profile.yaml`.

## 7. Testing

- `telegram.py`: mocked transport; request payloads; 429 retry; error
  messages without the token.
- `notifier.py`: every layout, HTML escaping, digest truncation, buttons.
- `store.py`: `job_ref` / `job_by_ref`.
- `inbox.py`: offset handling, chat filtering, unknown ref, resume.
- `letters/service.py`: document delivery with caption; caption length.
- Manual: real offer, digest and letter through the bot, button tap.

## 8. Migration

`profile.yaml` gains `telegram_token` and `telegram_chat_id` (already
known), loses the ntfy keys. Offers not yet notified because of the ntfy
quota are sent on the next run through Telegram (they were never marked
notified). The letters service is enabled once the listener is on
Telegram.
