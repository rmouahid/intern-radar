import json

import pytest

from intern_radar.candidate import (
    CANDIDATE_SCHEMA,
    SCHEMA_VERSION,
    CandidateError,
    candidate_text,
    check_candidate,
    diff,
    generate,
    load_candidate,
    parse_candidate,
    read_dossier,
    save_candidate,
    summarise,
)
from intern_radar.scorer import LLMError

DOSSIER = """# Career dossier
Master's student at Example Tech (2023-2028).
Internship at Acme (Jul-Aug 2025): built a RAG agent with Python and Docker,
cut answer time by 40%.
Project: vector search engine in Python.
"""


def profile_dict(**overrides):
    data = {
        "summary": "Engineering student building RAG systems.",
        "education": [
            {
                "id": "edu-example",
                "degree": "Master's in Computer Engineering",
                "school": "Example Tech",
                "dates": "2023-2028",
                "details": [],
            }
        ],
        "experiences": [
            {
                "id": "exp-acme",
                "title": "Infrastructure Intern",
                "organisation": "Acme",
                "dates": "Jul-Aug 2025",
                "context": "Self-hosted assistant for the infra team.",
                "actions": ["Built a RAG agent"],
                "results": ["Cut answer time by 40%"],
                "skills": ["Python", "Docker"],
                "keywords": ["RAG"],
            }
        ],
        "projects": [
            {
                "id": "proj-vector",
                "title": "Vector search engine",
                "organisation": "Personal",
                "dates": "2025",
                "context": "Search engine from scratch.",
                "actions": ["Implemented IVF search"],
                "results": [],
                "skills": ["Python"],
                "keywords": ["vector search"],
            }
        ],
        "skills": [
            {"name": "Python", "category": "Backend", "evidence": ["exp-acme"]},
            {"name": "Docker", "category": "Infrastructure", "evidence": ["exp-acme"]},
        ],
        "languages": [{"language": "English", "level": "C2"}],
        "extras": [],
    }
    data.update(overrides)
    return data


class FakeBackend:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def complete(self, prompt, schema):
        self.calls.append((prompt, schema))
        return self.answer


def test_parse_builds_typed_profile():
    candidate = parse_candidate(profile_dict())
    assert candidate.ids() == ["edu-example", "exp-acme", "proj-vector"]
    assert candidate.experiences[0].skills == ("Python", "Docker")
    assert summarise(candidate) == (
        "1 education, 1 experiences, 1 projects, 2 skills, 1 languages"
    )


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"summary": 3}, "profile.summary"),
        ({"experiences": [{"id": "x"}]}, r"experiences\[0\].title"),
        ({"skills": [{"name": "Go", "category": "B", "evidence": "exp"}]}, "evidence"),
        ({"projects": "none"}, "projects: expected a list"),
    ],
)
def test_parse_reports_the_invalid_field(overrides, message):
    with pytest.raises(CandidateError, match=message):
        parse_candidate(profile_dict(**overrides))


def test_duplicate_ids_are_rejected():
    data = profile_dict()
    data["projects"][0]["id"] = "exp-acme"
    with pytest.raises(CandidateError, match="duplicate ids: exp-acme"):
        parse_candidate(data)


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "candidate.json"
    candidate = parse_candidate(profile_dict())
    save_candidate(candidate, path)
    assert json.loads(path.read_text())["schema_version"] == SCHEMA_VERSION
    assert load_candidate(path) == candidate


def test_load_rejects_missing_files_and_old_schemas(tmp_path):
    with pytest.raises(CandidateError, match="not found"):
        load_candidate(tmp_path / "nope.json")
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"schema_version": 0, **profile_dict()}))
    with pytest.raises(CandidateError, match="generate-profile"):
        load_candidate(old)


def test_checks_flag_unsupported_facts():
    data = profile_dict()
    data["skills"].append({"name": "Kubernetes", "category": "Infra", "evidence": []})
    data["skills"].append({"name": "Docker", "category": "I", "evidence": ["exp-x"]})
    data["experiences"][0]["results"].append("Served 12000 users")
    warnings = check_candidate(parse_candidate(data), DOSSIER)
    assert "skill without evidence: Kubernetes" in warnings
    assert "skill not written as such in the dossier: Kubernetes" in warnings
    assert "skill Docker cites unknown ids: ['exp-x']" in warnings
    assert "exp-acme: number 12000 not in the dossier" in warnings
    assert check_candidate(parse_candidate(profile_dict()), DOSSIER) == []


def test_candidate_text_details_selected_items_only():
    candidate = parse_candidate(profile_dict())
    text = candidate_text(candidate, [candidate.projects[0]])
    assert "Implemented IVF search" in text
    assert "Built a RAG agent" not in text
    assert "Other experience: Infrastructure Intern (Acme)" in text
    assert "Languages: English (C2)" in text
    assert "Built a RAG agent" in candidate_text(candidate)


def test_diff_lists_added_removed_and_changed_items():
    old = parse_candidate(profile_dict())
    data = profile_dict()
    data["projects"] = []
    data["experiences"][0]["actions"].append("Wrote the runbook")
    data["skills"].append({"name": "Go", "category": "Backend", "evidence": []})
    assert diff(old, parse_candidate(data)) == [
        "- proj-vector",
        "~ exp-acme",
        "+ skill Go",
    ]


def test_generate_sends_dossier_schema_and_previous_ids():
    backend = FakeBackend(profile_dict())
    previous = parse_candidate(profile_dict())
    candidate = generate(backend, DOSSIER, previous)
    prompt, schema = backend.calls[0]
    assert schema is CANDIDATE_SCHEMA
    assert "<dossier>\n# Career dossier" in prompt
    assert "Reuse these existing ids" in prompt and "exp-acme" in prompt
    assert "Never infer" in prompt
    assert candidate == previous


def test_generate_turns_invalid_output_into_llm_error():
    with pytest.raises(LLMError, match="invalid profile"):
        generate(FakeBackend({"summary": "x", "education": "?"}), DOSSIER)


def test_read_dossier_appends_text_attachments(tmp_path):
    main = tmp_path / "career.md"
    main.write_text("Main text")
    folder = tmp_path / "career"
    folder.mkdir()
    (folder / "b-report.md").write_text("Report text")
    (folder / "a-notes.txt").write_text("Notes")
    (folder / "photo.png").write_bytes(b"\x89PNG")
    text = read_dossier(main, folder)
    assert text.startswith("Main text")
    assert text.index("a-notes.txt") < text.index("b-report.md")
    assert "photo" not in text


def test_read_dossier_errors(tmp_path, monkeypatch):
    with pytest.raises(CandidateError, match="career.example.md"):
        read_dossier(tmp_path / "career.md")
    main = tmp_path / "career.md"
    main.write_text("x")
    folder = tmp_path / "career"
    folder.mkdir()
    (folder / "report.pdf").write_bytes(b"%PDF")
    import builtins

    real_import = builtins.__import__

    def no_markitdown(name, *args, **kwargs):
        if name == "markitdown":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_markitdown)
    with pytest.raises(CandidateError, match="-E documents"):
        read_dossier(main, folder)


def test_select_items_ranks_by_matching_skills_and_keywords():
    from intern_radar.candidate import select_items

    candidate = parse_candidate(profile_dict())
    offer = "Build vector search for retrieval at scale in Python"
    assert [i.id for i in select_items(candidate, offer)] == [
        "proj-vector",
        "exp-acme",
    ]
    assert [i.id for i in select_items(candidate, "Docker RAG", limit=1)] == [
        "exp-acme"
    ]
    # No match: profile order is kept.
    assert [i.id for i in select_items(candidate, "Rust")] == [
        "exp-acme",
        "proj-vector",
    ]
