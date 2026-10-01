from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from intern_radar.dashboard import queries
from intern_radar.dashboard.app import Request
from intern_radar.dashboard.routes import Context, build_app
from intern_radar.store import Store
from tests.factories import make_assessment, make_job

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)  # a Thursday
WATCHED = (("Acme", "S", "greenhouse"), ("Quiet & Co", "A", "workday"))


def make_db(tmp_path) -> str:
    path = str(tmp_path / "c.db")
    store = Store(path)
    rows = (
        ("a1", "Acme", "ML Intern", "Berlin", 8.0, NOW - timedelta(days=1)),
        ("a2", "Acme", "ML Intern", "London", 8.0, NOW - timedelta(days=1)),
        ("a3", "Acme", "Data Intern", "Paris", 6.0, NOW - timedelta(days=9)),
        ("a4", "Acme", "Ops Intern", "Paris", 3.0, NOW - timedelta(days=9)),
        ("d1", "Disco AI", "AI Intern", "Madrid", 7.0, NOW - timedelta(days=3)),
    )
    for job_id, company, title, location, score, seen in rows:
        store.add(
            make_job(id=job_id, company=company, title=title, location=location,
                     tier="S" if company == "Acme" else "unlisted",
                     source="greenhouse" if company == "Acme" else "adzuna"),
            "pending", seen,
        )  # fmt: skip
        store.save_assessment(job_id, make_assessment(), score)
    store.set_application("a3", "applied", NOW)
    store.record_source_result("Quiet & Co", "HTTP 500", NOW - timedelta(days=2))
    store.close()
    return path


def test_companies_merge_configuration_and_database(tmp_path):
    db = queries.connect(make_db(tmp_path))
    rows = queries.companies(db, WATCHED, NOW.date())
    assert [r.name for r in rows] == ["Acme", "Disco AI", "Quiet & Co"]
    acme, disco, quiet = rows
    assert (acme.seen, acme.open, acme.applications, acme.best) == (4, 2, 1, 8.0)
    assert acme.watched and not disco.watched and disco.tier == "unlisted"
    assert quiet.seen == 0 and quiet.error == "HTTP 500" and quiet.last_new is None


def test_company_detail(tmp_path):
    db = queries.connect(make_db(tmp_path))
    detail = queries.company_detail(db, "Acme", WATCHED, NOW, weeks=3)
    assert detail.weekly == [
        ("2026-09-14", 0),
        ("2026-09-21", 2),  # a3 and a4, seen on Tuesday 22
        ("2026-09-28", 2),  # a1 and a2, seen on Wednesday 30
    ]
    assert [o.title for o in detail.offers] == ["ML Intern", "Data Intern"]
    assert detail.offers[0].other_places == 1
    assert [(t, s) for _, t, s, _ in detail.applications] == [
        ("Data Intern", "applied")
    ]
    assert queries.company_detail(db, "Nobody", WATCHED, NOW) is None


def test_company_routes(tmp_path):
    app = build_app(Context(make_db(tmp_path), clock=lambda: NOW, companies=WATCHED))
    listing = app.handle(Request("GET", "/companies", {})).body.decode()
    assert "Acme" in listing and "Découverte" in listing and "en échec" in listing
    filtered = app.handle(Request("GET", "/companies", {"q": "disco"})).body.decode()
    assert "Disco AI" in filtered and "Acme" not in filtered
    path = "/companies/" + quote("Quiet & Co", safe="")
    page = app.handle(Request("GET", path, {})).body.decode()
    assert "HTTP 500" in page and "Aucune offre ouverte" in page
    acme = app.handle(Request("GET", "/companies/Acme", {})).body.decode()
    assert "Offres ouvertes (2)" in acme and "Candidature envoyée" in acme
    assert app.handle(Request("GET", "/companies/Nobody", {})).status == 404
    store = Store(str(tmp_path / "c.db"))
    ref = store.job_ref("a1")
    store.close()
    offer = app.handle(Request("GET", f"/offers/{ref}", {})).body.decode()
    assert 'href="/companies/Acme"' in offer
