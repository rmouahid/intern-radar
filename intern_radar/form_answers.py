"""Answers to the remaining questions of an application form (one LLM call).

The in-browser filler sends the fields it could not fill by rule (label,
kind, options); the LLM answers from the candidate's facts only, choosing
among the given options. Questions that the candidate must answer personally
(legal consents and attestations, voluntary demographic or EEO questions) are
never answered, whatever the LLM returns.
"""

import json
import re
from dataclasses import dataclass
from typing import Any

from intern_radar.scorer import LLMBackend

KINDS = ("text", "textarea", "number", "select", "combobox", "radio", "checkbox")
MAX_FIELDS = 80
PERSONAL_RE = re.compile(
    r"consent|\bi agree\b|\bagree to\b|acknowledg|\bcertify\b|\battest|"
    r"\bdeclare\b|signature|privacy (policy|notice)|\bterms (of|and)\b|gender|"
    r"\bsex\b|pronoun|\brac(e|ial)\b|ethnic|hispanic|latin[oa]|veteran|"
    r"disabilit|sexual orientation|lgbt|transgender|religio|marital|"
    r"date of birth|birth ?date|\bage\b|social security|\bssn\b|"
    r"passport number|criminal|convict",
    re.IGNORECASE,
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "value": {"type": "string"},
                    "values": {"type": "array", "items": {"type": "string"}},
                    "review": {"type": "boolean"},
                },
                "required": ["id"],
            },
        }
    },
    "required": ["answers"],
}

PROMPT = """You fill an internship application form for the candidate below.
Answer each field from the candidate's facts only.

Rules:
- When a field lists options, answer with one of them, copied exactly
  ("values" with several options for checkbox groups, e.g. every language the
  candidate speaks). Prefer "Other" over a wrong option.
- For combobox fields without options, give the text to search (a country, a
  city, a school, a degree name, a month name...).
- Education questions (school, degree, start and end dates of studies,
  graduation) use the education_* facts; questions about the internship or
  availability use the internship_* facts. Never mix them.
- Work authorisation and sponsorship: use exactly the fixed answers given.
- Free-text questions: a short factual answer in the posting's language; set
  "review": true when the answer is a judgement or a guess.
- Leave a field out when the facts do not answer it. Never answer consents,
  attestations or demographic questions.
Return JSON: {{"answers": [{{"id": 0, "value": "...", "values": [], "review": false}}]}}

Offer: {company} — {title} — {location}

Candidate facts:
{facts}

Candidate profile:
{profile}

Fixed answers:
{fixed}

Fields:
{fields}
"""


@dataclass(frozen=True)
class FormField:
    id: int
    label: str
    kind: str
    options: tuple[str, ...] = ()
    required: bool = False


def parse_fields(data: Any) -> list[FormField]:
    """Fields sent by the filler; malformed entries are dropped."""
    fields = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict) or item.get("kind") not in KINDS:
            continue
        try:
            field_id = int(item["id"])
        except (KeyError, TypeError, ValueError):
            continue
        options = tuple(
            str(o).strip()[:200] for o in item.get("options") or () if str(o).strip()
        )[:300]
        fields.append(
            FormField(
                field_id,
                str(item.get("label") or "").strip()[:300],
                item["kind"],
                options,
                bool(item.get("required")),
            )
        )
    return fields[:MAX_FIELDS]


def is_personal(field: FormField) -> bool:
    """Questions the candidate answers personally (never by the LLM)."""
    return bool(PERSONAL_RE.search(field.label))


def _match(answer: str, options: tuple[str, ...]) -> str | None:
    """The option an answer names (exact, then case-insensitive, then prefix)."""
    if answer in options:
        return answer
    lowered = {o.lower(): o for o in options}
    if answer.lower() in lowered:
        return lowered[answer.lower()]
    for option in options:
        if option.lower().startswith(answer.lower()) and len(answer) >= 3:
            return option
    return None


def validate(fields: list[FormField], answers: Any) -> dict[int, dict[str, Any]]:
    """Keeps answers for known, non-personal fields and existing options."""
    by_id = {f.id: f for f in fields}
    result: dict[int, dict[str, Any]] = {}
    for item in answers if isinstance(answers, list) else []:
        if not isinstance(item, dict):
            continue
        field = by_id.get(item.get("id"))  # type: ignore[arg-type]
        if field is None or is_personal(field):
            continue
        review = bool(item.get("review"))
        if field.kind == "checkbox" and field.options:
            values = [
                matched
                for v in item.get("values") or [item.get("value") or ""]
                if (matched := _match(str(v), field.options))
            ]
            if values:
                result[field.id] = {
                    "values": list(dict.fromkeys(values)),
                    "review": review,
                }
            continue
        value = str(item.get("value") or "").strip()
        if not value:
            continue
        if field.options:
            matched = _match(value, field.options)
            if matched is None:
                continue
            value = matched
        result[field.id] = {"value": value[:2000], "review": review}
    return result


class FormAnswerer:
    def __init__(self, backend: LLMBackend) -> None:
        self._backend = backend

    def answer(
        self,
        kit: dict[str, Any],
        profile: str,
        fields: list[FormField],
    ) -> dict[int, dict[str, Any]]:
        asked = [f for f in fields if not is_personal(f)]
        if not asked:
            return {}
        fixed = "\n".join(
            f"- {a['question']}: {a['answer']}"
            for a in kit["answers"]
            if re.search(
                r"authori|sponsor|relocat|start date|duration", a["question"], re.I
            )
        )
        listing = json.dumps(
            [
                {
                    "id": f.id,
                    "label": f.label,
                    "kind": f.kind,
                    "options": list(f.options),
                }
                for f in asked
            ],
            ensure_ascii=False,
        )
        result = self._backend.complete(
            PROMPT.format(
                company=kit["offer"]["company"],
                title=kit["offer"]["title"],
                location=kit["offer"]["location"] or "not stated",
                facts=json.dumps(kit["fields"], ensure_ascii=False),
                profile=profile,
                fixed=fixed or "(none)",
                fields=listing,
            ),
            SCHEMA,
        )
        return validate(asked, result.get("answers"))
