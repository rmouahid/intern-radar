"""The "why this company / role" answer of application forms.

One LLM call drafts 80–120 words from the job posting and the structured
candidate profile; the letters' fact checks flag proper nouns and numbers
found in neither, and clichés, so that the candidate reviews them.
"""

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from intern_radar.candidate import Candidate, candidate_text, select_items
from intern_radar.description import clean_description
from intern_radar.letters.checks import blacklisted, unverified_tokens
from intern_radar.models import Job
from intern_radar.scorer import LLMBackend, LLMError
from intern_radar.store import Store

log = logging.getLogger(__name__)

WHY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
}

PROMPT = """Write the candidate's answer to the application-form question
"Why do you want to join {company} in this role?".

Rules:
- 80 to 120 words, first person, plain and specific, no superlatives.
- Link one or two concrete facts of the candidate to what this role and this
  company actually do, as described in the posting.
- Use only facts present in the candidate profile or in the job posting: no
  invented numbers, products, teams or values.
- Write in the language of the job posting (English if unsure).
Return JSON: {{"text": "..."}}

Candidate:
{candidate}

Job posting — {company}, {title}, {location}:
{description}
"""

DESCRIPTION_LIMIT = 6000


class WhyWriter:
    def __init__(self, backend: LLMBackend, candidate: Candidate) -> None:
        self._backend = backend
        self._candidate = candidate

    def write(self, job: Job) -> tuple[str, list[str]]:
        """The draft and its warnings (unverified tokens, clichés)."""
        description = clean_description(job.description)[:DESCRIPTION_LIMIT]
        selected = select_items(self._candidate, f"{job.title}\n{description}")
        profile = candidate_text(self._candidate, selected)
        result = self._backend.complete(
            PROMPT.format(
                company=job.company,
                title=job.title,
                location=job.location or "not stated",
                candidate=profile,
                description=description,
            ),
            WHY_SCHEMA,
        )
        text = str(result.get("text") or "").strip()
        if not text:
            raise LLMError("empty answer")
        sources = [candidate_text(self._candidate), job.title, job.company, description]
        warnings = [f"À vérifier : {t}" for t in unverified_tokens(text, sources)]
        warnings += [f"Formule creuse : {w}" for w in blacklisted(text)]
        return text, warnings


class WhyService:
    """Generates and stores the draft for an offer (background worker)."""

    def __init__(
        self,
        store: Store,
        writer: Callable[[], WhyWriter],
        clock: Callable[[], datetime],
    ) -> None:
        self._store = store
        self._writer = writer
        self._clock = clock

    def handle(self, job_id: str) -> str | None:
        job = self._store.get_job(job_id)
        if job is None:
            return None
        text, warnings = self._writer().write(job)
        self._store.save_why(job_id, text, warnings, self._clock())
        return text
