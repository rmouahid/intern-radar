import json
import subprocess
from datetime import date

import pytest

from intern_radar.scorer import (
    ASSESSMENT_SCHEMA,
    ClaudeCliBackend,
    LLMError,
    Scorer,
)
from tests.factories import make_assessment, make_job


class FakeBackend:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.prompts: list[str] = []

    def complete(self, prompt, schema):
        assert schema is ASSESSMENT_SCHEMA
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.result


def item(job_id, **overrides):
    values = {
        "job_id": job_id,
        "is_internship": True,
        "ai_relevance": 8,
        "dates_fit": "fits",
        "eligibility": "ok",
        "visa_note": "UK: GAE scheme via a sponsor",
        "language_ok": True,
        "summary": "Applied ML on LLM agents.",
    }
    values.update(overrides)
    return values


def make_scorer(backend):
    return Scorer(
        backend, "RAG and LLM student.", date(2027, 3, 8), date(2027, 8, 31), 4
    )


def test_prompt_contains_profile_window_and_truncated_jobs():
    backend = FakeBackend({"assessments": []})
    long_job = make_job(id="j1", description="x" * 5000)
    make_scorer(backend).assess([long_job])
    prompt = backend.prompts[0]
    assert "RAG and LLM student." in prompt
    assert "2027-03-08 to 2027-08-31" in prompt
    assert "at least 4 months" in prompt
    assert "Write visa_note and summary in French." in prompt
    assert "job_id: 1\n" in prompt
    assert "j1" not in prompt
    assert "x" * 3000 in prompt and "x" * 3001 not in prompt


def test_assess_maps_answers_by_job_id():
    backend = FakeBackend({"assessments": [item("2", ai_relevance=3), item("1")]})
    result = make_scorer(backend).assess([make_job(id="j1"), make_job(id="j2")])
    assert result == {
        "j1": make_assessment(),
        "j2": make_assessment(ai_relevance=3),
    }


def test_invalid_items_are_skipped():
    backend = FakeBackend(
        {
            "assessments": [
                item("1", dates_fit="maybe"),
                item("2", is_internship="yes"),
                item("3", ai_relevance=14),
                item("99"),
                {"job_id": "4"},
            ]
        }
    )
    jobs = [make_job(id=f"j{i}") for i in range(1, 6)]
    result = make_scorer(backend).assess(jobs)
    assert result == {"j3": make_assessment(ai_relevance=10)}


def test_assess_empty_list_does_not_call_backend():
    backend = FakeBackend(error=AssertionError("should not be called"))
    assert make_scorer(backend).assess([]) == {}


def test_backend_errors_propagate():
    backend = FakeBackend(error=LLMError("quota"))
    with pytest.raises(LLMError, match="quota"):
        make_scorer(backend).assess([make_job()])


class FakeRunner:
    def __init__(self, returncode=0, stdout="", stderr="", exc=None):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.exc = exc
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(
            command, self.returncode, self.stdout, self.stderr
        )


def test_cli_backend_builds_the_command_and_reads_structured_output():
    envelope = {
        "type": "result",
        "is_error": False,
        "structured_output": {"assessments": []},
    }
    runner = FakeRunner(stdout=json.dumps(envelope))
    backend = ClaudeCliBackend(model="haiku", runner=runner)
    assert backend.complete("PROMPT", {"type": "object"}) == {"assessments": []}
    command, kwargs = runner.calls[0]
    assert command[:4] == ["claude", "-p", "--model", "haiku"]
    assert "--json-schema" in command
    assert command[command.index("--json-schema") + 1] == '{"type": "object"}'
    assert command[command.index("--tools") + 1] == ""
    assert kwargs["input"] == "PROMPT"


@pytest.mark.parametrize(
    "runner, message",
    [
        (FakeRunner(returncode=1, stderr="usage limit reached"), "usage limit"),
        (FakeRunner(stdout="not json"), "invalid JSON"),
        (
            FakeRunner(stdout=json.dumps({"is_error": True, "result": "overloaded"})),
            "overloaded",
        ),
        (FakeRunner(exc=FileNotFoundError("cli")), "failed to run"),
        (FakeRunner(exc=subprocess.TimeoutExpired("cli", 600)), "failed to run"),
    ],
)
def test_cli_backend_failures_raise_llm_error(runner, message):
    with pytest.raises(LLMError, match=message):
        ClaudeCliBackend(runner=runner).complete("P", {})


def test_long_job_ids_are_replaced_by_batch_numbers():
    backend = FakeBackend({"assessments": [item("1")]})
    job = make_job(id="workday:nvidia:/job/US-CA-Santa-Clara/Deep-Learning_JR1")
    result = make_scorer(backend).assess([job])
    assert "workday:nvidia" not in backend.prompts[0]
    assert result == {job.id: make_assessment()}
