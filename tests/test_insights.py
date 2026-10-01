from datetime import UTC, datetime, timedelta

import pytest

from intern_radar.dashboard import queries
from intern_radar.dashboard.app import Request
from intern_radar.dashboard.routes import Context, build_app
from intern_radar.skills import find_skills
from intern_radar.store import Store
from tests.factories import make_assessment, make_job, make_profile

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    "text, present, absent",
    [
        ("Strong C++ and CUDA, PyTorch or JAX", {"C++", "CUDA", "PyTorch", "JAX"},
         {"C#"}),
        ("We use llama-cpp-python for local inference", {"Inference optimisation"},
         {"C++"}),
        ("JavaScript and TypeScript front end", {"JavaScript", "TypeScript"},
         {"Java"}),
        ("Experience with RAG, vector search (FAISS) and LangGraph agents",
         {"RAG", "Vector databases", "LangChain"}, set()),
        ("Build AI agents and multi-agent systems", {"Agents"}, set()),
        ("Kubernetes (k8s), Docker, AWS SageMaker, CI/CD with GitHub Actions",
         {"Kubernetes", "Docker", "AWS", "CI/CD"}, set()),
        ("travel agents and change agents", set(), {"Agents"}),
    ],
)  # fmt: skip
def test_vocabulary_detection(text, present, absent):
    found = find_skills(text)
    assert present <= found and not (absent & found)


def make_db(tmp_path) -> str:
    path = str(tmp_path / "skills.db")
    store = Store(path)
    offers = (
        ("a", "Acme", "PyTorch and Kubernetes", 8, NOW - timedelta(days=2)),
        ("b", "Beta", "PyTorch, Python", 9, NOW - timedelta(days=10)),
        ("c", "Gamma", "Kubernetes only", 3, NOW),  # not relevant enough
        ("d", "Acme", "PyTorch in Rust", 7, NOW - timedelta(days=120)),  # too old
    )
    for job_id, company, description, relevance, seen in offers:
        store.add(
            make_job(id=job_id, company=company, title=f"Intern {job_id}",
                     description=description),
            "pending", seen,
        )  # fmt: skip
        store.save_assessment(job_id, make_assessment(ai_relevance=relevance), 7.0)
    # The same posting in another place counts once.
    store.add(
        make_job(id="a2", company="Acme", title="Intern a", location="Elsewhere",
                 description="PyTorch and Kubernetes"),
        "pending", NOW,
    )  # fmt: skip
    store.save_assessment("a2", make_assessment(ai_relevance=8), 7.0)
    store.close()
    return path


def test_skill_demand_counts_relevant_groups_and_coverage(tmp_path):
    db = queries.connect(make_db(tmp_path))
    skills, offers = queries.skill_demand(db, "Python developer", NOW, 7)
    assert offers == 2
    by_name = {s.name: s for s in skills}
    assert skills[0].name == "PyTorch" and by_name["PyTorch"].offers == 2
    assert by_name["PyTorch"].share == 1.0 and not by_name["PyTorch"].covered
    assert by_name["Python"].covered and by_name["Kubernetes"].offers == 1
    assert "Rust" not in by_name
    assert [c for _, c, _ in by_name["PyTorch"].examples] == ["Acme", "Beta"]
    assert by_name["PyTorch"].trend == (0, 0, 0, 0, 1, 1)


def test_insights_page(tmp_path):
    path = make_db(tmp_path)
    profile = make_profile(candidate_summary="Python developer")
    app = build_app(Context(path, clock=lambda: NOW, profile=profile))
    body = app.handle(Request("GET", "/insights", {})).body.decode()
    assert "2 poste(s) pertinent(s)" in body and "profile.yaml" in body
    assert body.index("PyTorch") < body.index("Déjà dans ton profil")
    assert "Python · 50%" in body
    low = app.handle(Request("GET", "/insights", {"relevance": "3"})).body.decode()
    assert "3 poste(s) pertinent(s)" in low
    junk = app.handle(Request("GET", "/insights", {"relevance": "x"}))
    assert junk.status == 200
