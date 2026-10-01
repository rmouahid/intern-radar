"""Saved searches: Telegram alerts for new offers matching saved filters.

A saved search stores the offers page filters. After each run, every active
search is matched against the offers first seen after the search was saved;
each match is sent once (per offer and search), at most MAX_ALERTS per search
and run so that a broad search cannot flood the chat.
"""

import html
import logging
from collections.abc import Callable
from datetime import datetime
from urllib.parse import parse_qs

from intern_radar.dashboard.queries import OfferFilters, OfferRow, matching_offers
from intern_radar.notifier import (
    WORK_AUTHORISATION_LABELS,
    Message,
    Notifier,
    tier_label,
)
from intern_radar.store import SavedSearch, Store
from intern_radar.telegram import Button
from intern_radar.tracking import tracking_row

log = logging.getLogger(__name__)
e = html.escape
MAX_ALERTS = 5


def search_filters(search: SavedSearch, default_days: int) -> OfferFilters:
    query = {k: v[-1] for k, v in parse_qs(search.query).items()}
    query.pop("page", None)
    return OfferFilters.from_query(query, default_days)


def format_search_alert(search: SavedSearch, row: OfferRow) -> Message:
    lines = [
        f"🔔 <b>Recherche « {e(search.name)} »</b>",
        f"<b>{e(row.company[:80])} · {tier_label(row.tier)}</b>",
        f"{e(row.title[:200])}",
        f"📍  {e(row.location[:100] or 'Lieu non précisé')}",
        f"⭐  {row.score:.1f} / 10 · "
        f"{WORK_AUTHORISATION_LABELS.get(row.work_authorisation, '')}",
    ]
    rows: tuple[tuple[Button, ...], ...] = ()
    if row.url.startswith(("https://", "http://")):
        rows = ((Button("🔗 Voir l'offre", url=row.url),),)
    rows += (tracking_row(row.application, row.ref),)
    return Message("\n".join(lines), rows)


class SearchAlerts:
    def __init__(
        self,
        store: Store,
        notifier: Notifier,
        clock: Callable[[], datetime],
        default_days: int = 60,
    ) -> None:
        self._store = store
        self._notifier = notifier
        self._clock = clock
        self._default_days = default_days

    def check(self) -> int:
        """Sends the new matches of every active search; returns how many."""
        now = self._clock()
        sent = 0
        for search in self._store.searches(active_only=True):
            filters = search_filters(search, self._default_days)
            known = self._store.search_hit_ids(search.id)
            rows = [
                row
                for row in matching_offers(self._store._db, filters, now.date())
                if row.job_id not in known and row.first_seen >= search.created_at
            ]
            for row in rows[:MAX_ALERTS]:
                try:
                    self._notifier.send(format_search_alert(search, row))
                except Exception:
                    log.exception("alert for search %s not sent", search.id)
                    break  # retried on the next run
                self._store.add_search_hit(search.id, row.job_id, now)
                sent += 1
        return sent
