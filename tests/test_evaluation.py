from datetime import UTC, datetime

import pytest

from intern_radar.dashboard.app import Request
from intern_radar.dashboard.routes import Context, build_app
from intern_radar.evaluation import (
    EvalOffer,
    Prediction,
    Run,
    confusion,
    load_offers,
    render_report,
    run_prompt,
    sample_offers,
    save_offers,
    usage_recorder,
)
from intern_radar.scorer import INSTRUCTIONS, INSTRUCTIONS_V2, PROMPTS, Scorer
from intern_radar.store import Store
from tests.factories import make_assessment, make_job, make_profile

NOW = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)
HEADERS = {"host": "radar", "origin": "http://radar"}


def scored_db(tmp_path, scores):
    path = str(tmp_path / "radar.db")
    store = Store(path)
    for n, score in enumerate(scores):
        job = make_job(id=f"greenhouse:acme:{n}")
        store.add(job, "pending", NOW)
        store.save_assessment(job.id, make_assessment(), score)
    store.add(make_job(id="greenhouse:acme:untriaged"), "pending", NOW)
    store.close()
    return path


def offer(n: int, label=None) -> EvalOffer:
    return EvalOffer(
        id=f"greenhouse:acme:{n}", company="Acme", tier="A", title=f"ML Intern {n}",
        location="London, UK", url=f"https://example.com/{n}", posted_at="2026-10-01",
        description="Build LLM agents.", label=label,
    )  # fmt: skip


def test_sample_draws_every_score_band_and_only_triaged_offers(tmp_path):
    path = scored_db(tmp_path, [9.0] * 5 + [6.0] * 5 + [3.0] * 5 + [None] * 5)
    drawn = sample_offers(path, 10, digest=5.5, immediate=7.5, seed=1)
    scores = {o.id: o for o in drawn}
    assert len(drawn) == 10
    assert "greenhouse:acme:untriaged" not in scores
    numbers = [int(o.id.rsplit(":", 1)[1]) for o in drawn]
    assert sum(n < 5 for n in numbers) == 3  # high band: 30 %
    assert sum(5 <= n < 10 for n in numbers) == 3  # middle band: 30 %
    assert sum(n >= 10 for n in numbers) == 4  # low or excluded: 40 %
    assert sample_offers(path, 10, 5.5, 7.5, seed=1) == drawn  # reproducible


def test_offers_round_trip_with_their_labels(tmp_path):
    path = tmp_path / "eval" / "offers.jsonl"
    save_offers(path, [offer(1, True), offer(2)])
    assert load_offers(path) == [offer(1, True), offer(2)]


def test_confusion_counts_only_labelled_offers():
    labels = {"a": True, "b": True, "c": False, "d": False}
    predictions = [
        Prediction("a", 8.0, 8, True, True),
        Prediction("b", 4.0, 3, False, False),
        Prediction("c", 6.0, 6, True, False),
        Prediction("d", None, None, False, False),
        Prediction("unlabelled", 9.0, 9, True, True),
    ]
    m = confusion(labels, predictions, lambda p: p.shown)
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (1, 1, 1, 1)
    assert m["precision"] == m["recall"] == m["f1"] == 0.5


class Backend:
    def __init__(self, relevance: dict[str, int]):
        self.relevance = relevance
        self.prompts: list[str] = []

    def complete(self, prompt, schema):
        self.prompts.append(prompt)
        numbers = [
            line.split(": ")[1]
            for line in prompt.splitlines()
            if line.startswith("--- job_id")
        ]
        titles = [
            line[7:] for line in prompt.splitlines() if line.startswith("Title: ")
        ]
        return {"assessments": [
            {"job_id": n, "is_internship": True,
             "ai_relevance": self.relevance.get(t, 2),
             "dates_fit": "fits", "eligibility": "ok", "visa_note": "",
             "work_authorisation": "free", "language_ok": True, "summary": ""}
            for n, t in zip(numbers, titles, strict=True)
        ]}  # fmt: skip


def test_run_scores_like_the_pipeline_in_batches_of_ten():
    profile = make_profile()
    backend = Backend({"ML Intern 3": 9})
    scorer = Scorer(backend, "summary", profile.window_start, profile.window_end, 4)
    predictions = run_prompt([offer(n) for n in range(12)], scorer, profile)
    assert len(backend.prompts) == 2  # 10 + 2
    by_id = {p.id: p for p in predictions}
    assert by_id["greenhouse:acme:3"].shown
    assert not by_id["greenhouse:acme:4"].shown  # relevance 2 < min relevance


def test_prompt_variants_differ_only_on_ai_relevance():
    assert PROMPTS == {"v1": INSTRUCTIONS, "v2": INSTRUCTIONS_V2}
    assert "9-10: LLM applications, RAG, agents" in INSTRUCTIONS_V2
    assert (
        INSTRUCTIONS_V2.split("- dates_fit")[1] == INSTRUCTIONS.split("- dates_fit")[1]
    )


def test_usage_is_summed_over_calls():
    totals, record = usage_recorder()
    record({"input": 100, "output": 20, "cost": 0.01})
    record({"input": 50, "output": 10, "cost": 0.02})
    assert totals == {"tokens": 180, "cost": pytest.approx(0.03), "calls": 2}


def test_report_has_one_row_per_run_and_decision():
    offers = [offer(1, True), offer(2, False), offer(3)]
    run = Run("v2", "haiku", [Prediction(offer(1).id, 8.0, 9, True, True),
                              Prediction(offer(2).id, 2.0, 2, False, False)],
              {"tokens": 1200, "cost": 0.05})  # fmt: skip
    report = render_report(offers, [run], "poetry run intern-radar eval report")
    assert "2 offers labelled by hand (1 the candidate wants to see, 1 not)" in report
    assert (
        "| v2 | haiku | shown | 1.00 | 1.00 | 1.00 | 1 | 0 | 0 | 1,200 | $0.05 |"
        in report
    )
    assert "| v2 | haiku | notified |" in report


def test_labelling_page_walks_through_the_offers(tmp_path):
    path = tmp_path / "offers.jsonl"
    save_offers(path, [offer(1), offer(2), offer(3)])
    app = build_app(Context(scored_db(tmp_path, []), eval_path=path))

    body = app.handle(Request("GET", "/eval", {})).body.decode()
    assert "0 / 3 étiquetées" in body and "ML Intern 1" in body

    response = app.handle(Request("POST", "/eval/0", {}, {"label": "yes"}, HEADERS))
    assert response.status == 303
    app.handle(Request("POST", "/eval/1", {}, {"label": "skip"}, HEADERS))
    body = app.handle(Request("GET", "/eval", {})).body.decode()
    assert "ML Intern 3" in body  # the skipped offer comes back last
    app.handle(Request("POST", "/eval/2", {}, {"label": "no"}, HEADERS))
    body = app.handle(Request("GET", "/eval", {})).body.decode()
    assert "ML Intern 2" in body
    assert [o.label for o in load_offers(path)] == [True, None, False]


def test_labelling_needs_a_sample_and_the_same_origin(tmp_path):
    app = build_app(Context(scored_db(tmp_path, []), eval_path=tmp_path / "none.jsonl"))
    assert (
        "intern-radar eval sample"
        in app.handle(Request("GET", "/eval", {})).body.decode()
    )
    path = tmp_path / "offers.jsonl"
    save_offers(path, [offer(1)])
    app = build_app(Context(scored_db(tmp_path, []), eval_path=path))
    assert app.handle(Request("POST", "/eval/0", {}, {"label": "yes"})).status == 403
