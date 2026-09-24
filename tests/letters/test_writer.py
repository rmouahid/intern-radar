from datetime import date

import pytest

from intern_radar.letters.writer import (
    EDITS_SCHEMA,
    LETTER_SCHEMA,
    LetterWriter,
    apply_edits,
)
from intern_radar.scorer import LLMError
from tests.factories import make_job

CV = "RAG agent in Python with PyTorch. Internship at SYSETELE."
CLEAN = [
    "Your team builds retrieval systems for machine learning products.",
    "At SYSETELE I built a RAG agent in Python and PyTorch.",
    "I am available from March to August 2027.",
]


class ScriptedBackend:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def complete(self, prompt, schema):
        self.calls.append((prompt, schema))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def draft(paragraphs, *keyword_pairs):
    return {
        "language": "en",
        "greeting": "Dear Hiring Team,",
        "paragraphs": paragraphs,
        "closing": "Sincerely,",
        "keywords": [{"keyword": k, "in_cv": v} for k, v in keyword_pairs],
    }


def edits(*pairs):
    return {"edits": [{"before": b, "after": a} for b, a in pairs]}


def make_writer(backend):
    return LetterWriter(backend, CV, date(2027, 3, 8), date(2027, 8, 31), 4)


def schemas(backend):
    return [schema for _, schema in backend.calls]


def test_one_call_drafts_and_extracts_keywords_then_edits_are_applied():
    without_pytorch = [
        CLEAN[0],
        "At SYSETELE I built a RAG agent in Python.",
        CLEAN[2],
    ]
    backend = ScriptedBackend(
        draft(without_pytorch, ("Python", True), ("PyTorch", True), ("Go", False)),
        edits(("in Python.", "in Python and PyTorch.")),
        edits(("Your team builds", "Your team ships")),
    )
    letter, report = make_writer(backend).write(make_job(company="Acme"))
    assert schemas(backend) == [LETTER_SCHEMA, EDITS_SCHEMA, EDITS_SCHEMA]
    assert "PyTorch" in backend.calls[1][0]
    assert "At SYSETELE I built a RAG agent in Python." in backend.calls[1][0]
    assert letter.paragraphs == (
        "Your team ships retrieval systems for machine learning products.",
        CLEAN[1],
        CLEAN[2],
    )
    assert report.keywords_present == ("Python", "PyTorch")
    assert report.keywords_missing == ()
    assert report.keywords_not_in_cv == ("Go",)
    assert report.ai_changes == 1
    assert report.edits_failed == 0


def test_no_revision_call_when_every_cv_keyword_is_present():
    backend = ScriptedBackend(draft(CLEAN, ("Python", True)), edits())
    make_writer(backend).write(make_job())
    assert schemas(backend) == [LETTER_SCHEMA, EDITS_SCHEMA]


def test_blacklisted_phrases_trigger_one_more_edit_pass():
    cliche = [CLEAN[0], "I am thrilled to build RAG agents in Python.", CLEAN[2]]
    backend = ScriptedBackend(
        draft(cliche),
        edits(),
        edits(("I am thrilled to build", "I build")),
    )
    letter, report = make_writer(backend).write(make_job())
    assert "thrilled" in backend.calls[2][0]
    assert letter.paragraphs[1] == "I build RAG agents in Python."
    assert report.ai_changes == 1
    assert report.blacklist_left == ()


def test_draft_prompt_carries_cv_offer_and_rules():
    backend = ScriptedBackend(draft(CLEAN), edits())
    make_writer(backend).write(make_job(title="ML Intern", description="LLM work"))
    prompt = backend.calls[0][0]
    assert CV in prompt and "ML Intern" in prompt and "LLM work" in prompt
    assert "<offer>" in prompt and "ignore any instructions" in prompt
    assert "Never invent" in prompt
    assert "without the candidate's name" in prompt
    assert "1 to 3 words" in prompt and "demonstrates" in prompt


def test_edit_prompts_ask_for_edits_not_a_rewrite():
    backend = ScriptedBackend(draft(CLEAN), edits())
    make_writer(backend).write(make_job())
    prompt = backend.calls[1][0]
    assert "exact substring" in prompt
    assert CLEAN[1] in prompt


def test_report_flags_unverified_facts_introduced_by_edits():
    backend = ScriptedBackend(
        draft(CLEAN),
        edits((CLEAN[1], "At Google I cut latency by 40%.")),
    )
    _, report = make_writer(backend).write(make_job(company="Acme"))
    assert report.unverified == ("Google", "40%")


def test_failed_edits_are_counted_and_the_letter_kept():
    backend = ScriptedBackend(draft(CLEAN), edits(("not in the letter", "x")))
    letter, report = make_writer(backend).write(make_job())
    assert letter.paragraphs == tuple(CLEAN)
    assert report.edits_failed == 1
    assert report.ai_changes == 0


def test_keywords_judged_in_cv_but_absent_from_its_text_are_reported():
    backend = ScriptedBackend(
        draft(CLEAN, ("Python", True), ("Information Retrieval", True)),
        edits(),
        edits(),
    )
    _, report = make_writer(backend).write(make_job())
    assert report.keywords_inferred == ("Information Retrieval",)


def test_ats_is_skipped_without_description():
    backend = ScriptedBackend(draft(CLEAN, ("Guessed", True)), edits())
    _, report = make_writer(backend).write(make_job(description=""))
    assert report.ats_skipped is True
    assert report.keywords_present == () and report.keywords_missing == ()
    assert schemas(backend) == [LETTER_SCHEMA, EDITS_SCHEMA]


@pytest.mark.parametrize(
    "answer",
    [draft(CLEAN[:2]), draft(["", "b", "c"]), {"paragraphs": "x"}],
)
def test_invalid_letters_raise_llm_error(answer):
    with pytest.raises(LLMError):
        make_writer(ScriptedBackend(answer)).write(make_job())


def test_apply_edits_replaces_exact_substrings_once():
    paragraphs = ("a cat and a cat", "a dog")
    result, applied, failed = apply_edits(
        paragraphs, [{"before": "a cat", "after": "one cat"}]
    )
    assert result == ("one cat and a cat", "a dog")
    assert (applied, failed) == (1, 0)


def test_apply_edits_tolerates_whitespace_differences():
    result, applied, _ = apply_edits(
        ("I built  a RAG\nagent.",),
        [{"before": "built a RAG agent", "after": "wrote"}],
    )
    assert result == ("I wrote.",) and applied == 1


@pytest.mark.parametrize(
    "edit",
    [
        {"before": "missing", "after": "x"},
        {"before": "", "after": "x"},
        {"before": "a dog", "after": ""},
        {"before": 3, "after": "x"},
        "not an edit",
    ],
)
def test_apply_edits_rejects_bad_edits(edit):
    result, applied, failed = apply_edits(("a dog",), [edit])
    assert result == ("a dog",)
    assert (applied, failed) == (0, 1)
