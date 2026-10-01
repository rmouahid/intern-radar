from datetime import UTC, datetime, timedelta

from intern_radar.dashboard.app import Request
from intern_radar.dashboard.routes import Context, build_app
from intern_radar.searches import MAX_ALERTS, SearchAlerts
from intern_radar.store import Store
from tests.factories import make_assessment, make_job

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
HEADERS = {"host": "radar", "origin": "http://radar"}


class FakeNotifier:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, message):
        if self.fail:
            raise RuntimeError("telegram down")
        self.sent.append(message)


def add_offer(store, job_id, seen, location="Berlin", title="AI Intern", score=8.0):
    store.add(
        make_job(id=job_id, company=f"Co {job_id}", title=title, location=location,
                 posted_at=None),
        "pending", seen,
    )  # fmt: skip
    store.save_assessment(job_id, make_assessment(), score)


def test_alerts_once_per_offer_and_only_for_offers_seen_after_saving():
    store = Store(":memory:")
    add_offer(store, "before", NOW - timedelta(days=1))
    store.add_search("Allemagne", "region=dach", NOW)
    add_offer(store, "berlin", NOW + timedelta(hours=1))
    add_offer(store, "london", NOW + timedelta(hours=1), location="London, UK")
    add_offer(store, "low", NOW + timedelta(hours=1), score=3.0)
    notifier = FakeNotifier()
    alerts = SearchAlerts(store, notifier, lambda: NOW + timedelta(hours=2))
    assert alerts.check() == 1
    text = notifier.sent[0].html
    assert "Recherche « Allemagne »" in text and "Co berlin" in text
    assert notifier.sent[0].buttons[0][0].label == "🔗 Voir l'offre"
    assert alerts.check() == 0  # already sent
    assert store.searches()[0].hits == 1


def test_alerts_are_capped_per_run_and_paused_searches_are_skipped():
    store = Store(":memory:")
    search_id = store.add_search("Tout", "", NOW)
    for i in range(MAX_ALERTS + 2):
        add_offer(store, f"j{i}", NOW + timedelta(minutes=1), title=f"AI Intern {i}")
    notifier = FakeNotifier()
    alerts = SearchAlerts(store, notifier, lambda: NOW + timedelta(hours=1))
    assert alerts.check() == MAX_ALERTS
    assert alerts.check() == 2
    store.set_search_active(search_id, False)
    add_offer(store, "late", NOW + timedelta(minutes=2), title="Late Intern")
    assert alerts.check() == 0


def test_failed_sends_are_retried_on_the_next_run():
    store = Store(":memory:")
    store.add_search("Tout", "", NOW)
    add_offer(store, "j1", NOW + timedelta(minutes=1))
    assert SearchAlerts(store, FakeNotifier(fail=True), lambda: NOW).check() == 0
    assert store.search_hit_ids(1) == set()
    assert SearchAlerts(store, FakeNotifier(), lambda: NOW).check() == 1


def test_search_routes(tmp_path):
    path = str(tmp_path / "s.db")
    Store(path).close()
    app = build_app(Context(path, clock=lambda: NOW))
    offers = app.handle(Request("GET", "/offers", {"region": "dach", "page": "2"}))
    assert 'action="/searches"' in offers.body.decode()
    response = app.handle(
        Request(
            "POST", "/searches", {},
            {"name": "DACH", "query": "region=dach&page=2&evil=1"}, HEADERS,
        )
    )  # fmt: skip
    assert response.headers == (("Location", "/searches?done=search_saved"),)
    store = Store(path)
    (saved,) = store.searches()
    store.close()
    assert saved.query == "min=5.5&region=dach&days=60"
    body = app.handle(Request("GET", "/searches", {})).body.decode()
    assert "DACH" in body and "Mettre en pause" in body
    post = Request("POST", f"/searches/{saved.id}/toggle", {}, {}, HEADERS)
    app.handle(post)
    assert "Réactiver" in app.handle(Request("GET", "/searches", {})).body.decode()
    unnamed = Request("POST", "/searches", {}, {"name": " ", "query": ""}, HEADERS)
    assert app.handle(unnamed).headers == (("Location", "/searches?done=search_name"),)
    bad = Request("POST", f"/searches/{saved.id}/explode", {}, {}, HEADERS)
    assert app.handle(bad).status == 404
    app.handle(Request("POST", f"/searches/{saved.id}/delete", {}, {}, HEADERS))
    assert (
        "Aucune recherche" in app.handle(Request("GET", "/searches", {})).body.decode()
    )
    foreign = Request("POST", "/searches", {}, {"name": "x"})
    assert app.handle(foreign).status == 403
