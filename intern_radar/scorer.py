"""LLM assessment of candidate internships through the claude CLI."""

import json
import subprocess
from collections.abc import Callable
from datetime import date
from typing import Any, Protocol

from intern_radar.models import (
    DATES_FIT_VALUES,
    ELIGIBILITY_VALUES,
    Assessment,
    Job,
)

DESCRIPTION_LIMIT = 3000

ASSESSMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                    "is_internship": {"type": "boolean"},
                    "ai_relevance": {"type": "integer", "minimum": 0, "maximum": 10},
                    "dates_fit": {"type": "string", "enum": list(DATES_FIT_VALUES)},
                    "eligibility": {
                        "type": "string",
                        "enum": list(ELIGIBILITY_VALUES),
                    },
                    "visa_note": {"type": "string"},
                    "language_ok": {"type": "boolean"},
                    "summary": {"type": "string"},
                },
                "required": [
                    "job_id",
                    "is_internship",
                    "ai_relevance",
                    "dates_fit",
                    "eligibility",
                    "visa_note",
                    "language_ok",
                    "summary",
                ],
            },
        }
    },
    "required": ["assessments"],
}

INSTRUCTIONS = """You assess internship offers for one candidate.

Candidate:
{summary}

Internship window: {start} to {end}. Minimum duration: {months} months.

Return one assessment per job below, with the same job_id:
- is_internship: true only for an internship, co-op or placement for students.
- ai_relevance: 0-10, how close the role is to AI/ML engineering (LLMs, RAG,
  agents, ML infrastructure, data) and to the candidate's skills.
- dates_fit: "fits" if it can start inside the window and last
  at least {months} months within it; "too_short_extendable" if it starts
  inside the window but lasts less than {months} months (e.g. a 12-week summer
  internship); "incompatible" if it cannot start inside the window (e.g. a
  January-April co-op, a fall internship); "unknown" if the posting does not
  say.
- eligibility: "phd_only" if a PhD enrolment is required;
  "local_students_only" if applicants must be enrolled at a university in the
  job's country; "ok" if a student from a French engineering school can
  apply; "unknown" otherwise.
- visa_note: one short sentence on the work authorisation a French citizen
  needs for this location, or what the posting says about sponsorship.
- language_ok: false if the role requires a language other than English,
  Spanish or French.
- summary: one sentence describing the role.
Write visa_note and summary in French.

Jobs:
"""


class LLMError(Exception):
    """The LLM backend could not produce an answer."""


class LLMBackend(Protocol):
    def complete(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]: ...


class ClaudeCliBackend:
    """Runs `claude -p` with structured output, using the logged-in session."""

    def __init__(
        self,
        model: str = "haiku",
        timeout: int = 600,
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        self._model = model
        self._timeout = timeout
        self._runner = runner

    def complete(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        command = [
            "claude",
            "-p",
            "--model",
            self._model,
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(schema),
            "--tools",
            "",
            "--no-session-persistence",
            "--strict-mcp-config",
        ]
        try:
            proc = self._runner(
                command,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LLMError(f"claude CLI failed to run: {exc}") from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:300]
            raise LLMError(f"claude CLI exited with {proc.returncode}: {detail}")
        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise LLMError("claude CLI returned invalid JSON") from exc
        output = envelope.get("structured_output")
        if envelope.get("is_error") or not isinstance(output, dict):
            detail = str(envelope.get("result", ""))[:300]
            raise LLMError(f"claude CLI returned no structured output: {detail}")
        return output


def _parse(item: Any) -> Assessment | None:
    if not isinstance(item, dict):
        return None
    try:
        booleans = (item["is_internship"], item["language_ok"])
        relevance = item["ai_relevance"]
        dates_fit, eligibility = item["dates_fit"], item["eligibility"]
        visa_note, summary = item["visa_note"], item["summary"]
    except KeyError:
        return None
    if not all(isinstance(value, bool) for value in booleans):
        return None
    if not isinstance(relevance, int) or isinstance(relevance, bool):
        return None
    if dates_fit not in DATES_FIT_VALUES or eligibility not in ELIGIBILITY_VALUES:
        return None
    return Assessment(
        is_internship=item["is_internship"],
        ai_relevance=min(max(relevance, 0), 10),
        dates_fit=dates_fit,
        eligibility=eligibility,
        visa_note=str(visa_note),
        language_ok=item["language_ok"],
        summary=str(summary),
    )


class Scorer:
    def __init__(
        self,
        backend: LLMBackend,
        candidate_summary: str,
        window_start: date,
        window_end: date,
        min_months: int,
    ) -> None:
        self._backend = backend
        self._header = INSTRUCTIONS.format(
            summary=candidate_summary.strip(),
            start=window_start.isoformat(),
            end=window_end.isoformat(),
            months=min_months,
        )

    def build_prompt(self, jobs: list[Job]) -> str:
        # Jobs are numbered 1..n: long source ids (Workday paths) are easy for
        # the LLM to mangle, which would leave the job unscored.
        blocks = [
            f"--- job_id: {number}\n"
            f"Company: {job.company}\n"
            f"Title: {job.title}\n"
            f"Location: {job.location or 'not stated'}\n"
            f"Description:\n{job.description[:DESCRIPTION_LIMIT]}\n"
            for number, job in enumerate(jobs, start=1)
        ]
        return self._header + "\n".join(blocks)

    def assess(self, jobs: list[Job]) -> dict[str, Assessment]:
        if not jobs:
            return {}
        result = self._backend.complete(self.build_prompt(jobs), ASSESSMENT_SCHEMA)
        by_number = {str(number): job.id for number, job in enumerate(jobs, 1)}
        assessments: dict[str, Assessment] = {}
        for item in result.get("assessments", []):
            parsed = _parse(item)
            number = str(item.get("job_id", "")) if isinstance(item, dict) else ""
            if parsed is not None and number in by_number:
                assessments[by_number[number]] = parsed
        return assessments
