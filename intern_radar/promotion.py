"""Promotes an evening-digest offer to a full notification on request."""

from collections.abc import Callable
from datetime import UTC, datetime

from intern_radar.chance import Chance
from intern_radar.models import ScoredJob
from intern_radar.notifier import Notifier, format_immediate
from intern_radar.store import Store


class Promoter:
    """Sends a digest offer, with its whole posting group, as an immediate one."""

    def __init__(
        self,
        store: Store,
        notifier: Notifier,
        letters: bool,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        chance: Callable[[ScoredJob], Chance | None] | None = None,
        resumes: bool = False,
    ) -> None:
        self._store = store
        self._notifier = notifier
        self._letters = letters
        self._clock = clock
        self._chance = chance
        self._resumes = resumes

    def promote(self, ref: int) -> bool:
        """False when `ref` is not a scored offer. Sending again is allowed."""
        members = self._store.group_by_ref(ref)
        if not members:
            return False
        lead, *siblings = members
        callback = f"L:{ref}" if self._letters else None
        chance = self._chance(lead) if self._chance else None
        cv = f"C:{ref}" if self._resumes else None
        self._notifier.send(format_immediate(lead, callback, siblings, chance, cv))
        now = self._clock()
        for member in members:
            self._store.mark_notified(member.job.id, now)
        return True
