"""Hand edits of generated letters and CVs.

The services store the document's structure next to its report (`letter`,
`resume` keys); an edit rebuilds the document from it, renders the PDF again
with the offer's country convention, overwrites the file and keeps the
previous report under `previous`. Re-sending goes through the services, which
deliver the stored file.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from intern_radar.candidate import Candidate, Item
from intern_radar.config import Contact
from intern_radar.conventions import convention_for
from intern_radar.letters import pdf as letter_pdf
from intern_radar.letters.writer import Letter
from intern_radar.resume import pdf as resume_pdf
from intern_radar.resume.writer import Resume
from intern_radar.store import Store

MAX_TEXT = 2000  # characters per edited field
MAX_BULLETS = 6


class EditError(Exception):
    """The document cannot be edited (missing, or generated before edits)."""


# --- serialisation ---------------------------------------------------------------


def letter_to_dict(letter: Letter) -> dict[str, Any]:
    return {
        "language": letter.language,
        "greeting": letter.greeting,
        "paragraphs": list(letter.paragraphs),
        "closing": letter.closing,
    }


def letter_from_report(report: dict[str, Any]) -> Letter:
    data = report.get("letter")
    if isinstance(data, dict):
        return Letter(
            str(data.get("language") or "en"),
            str(data.get("greeting") or ""),
            tuple(str(p) for p in data.get("paragraphs") or ()),
            str(data.get("closing") or ""),
        )
    # Letters generated before the structure was stored: rebuild from text.
    blocks = [b.strip() for b in str(report.get("text") or "").split("\n\n")]
    blocks = [b for b in blocks if b]
    if len(blocks) < 3:
        raise EditError("lettre sans texte enregistré")
    french = blocks[0].lower().startswith(("madame", "monsieur", "bonjour"))
    return Letter("fr" if french else "en", blocks[0], tuple(blocks[1:-1]), blocks[-1])


def resume_to_dict(resume: Resume) -> dict[str, Any]:
    def entries(pairs):
        return [{"id": item.id, "bullets": list(bullets)} for item, bullets in pairs]

    return {
        "language": resume.language,
        "headline": resume.headline,
        "summary": resume.summary,
        "experiences": entries(resume.experiences),
        "projects": entries(resume.projects),
        "skills": [[category, list(names)] for category, names in resume.skills],
    }


def resume_from_dict(data: dict[str, Any], candidate: Candidate) -> Resume:
    """The stored CV; items no longer in the candidate profile are left out."""
    by_id: dict[str, Item] = {item.id: item for item in candidate.items}

    def entries(values) -> tuple[tuple[Item, tuple[str, ...]], ...]:
        return tuple(
            (by_id[v["id"]], tuple(str(b) for b in v.get("bullets") or ()))
            for v in values or ()
            if isinstance(v, dict) and v.get("id") in by_id
        )

    return Resume(
        str(data.get("language") or "en"),
        str(data.get("headline") or ""),
        str(data.get("summary") or ""),
        entries(data.get("experiences")),
        entries(data.get("projects")),
        tuple(
            (str(c), tuple(str(n) for n in names))
            for c, names in data.get("skills") or ()
        ),
    )


# --- edits -----------------------------------------------------------------------


def _clean(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())[:MAX_TEXT]


def _history(report: dict[str, Any], now: datetime) -> dict[str, Any]:
    previous = {k: v for k, v in report.items() if k != "previous"}
    return {"previous": previous, "edited_at": now.isoformat()}


class DocumentEditor:
    def __init__(
        self,
        store: Store,
        contact: Contact,
        candidate: Callable[[], Candidate] | None = None,
    ) -> None:
        self._store = store
        self._contact = contact
        self._candidate = candidate

    def letter(self, job_id: str) -> Letter:
        saved = self._store.letter(job_id)
        if saved is None:
            raise EditError("aucune lettre générée")
        return letter_from_report(saved[1])

    def edit_letter(
        self,
        job_id: str,
        greeting: str,
        paragraphs: list[str],
        closing: str,
        now: datetime,
    ) -> Path:
        job = self._store.get_job(job_id)
        saved = self._store.letter(job_id)
        if job is None or saved is None:
            raise EditError("aucune lettre générée")
        path, report = Path(saved[0]), saved[1]
        old = letter_from_report(report)
        kept = tuple(p for p in (_clean(p) for p in paragraphs) if p)
        if not kept or not greeting.strip() or not closing.strip():
            raise EditError("la formule d'appel, un paragraphe et la formule finale "
                            "sont obligatoires")  # fmt: skip
        letter = Letter(old.language, _clean(greeting), kept, _clean(closing))
        convention = convention_for(job.location)
        data, dropped, pages = letter_pdf.render(
            letter, job, self._contact, now.date(), convention
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        new = {
            **report,
            **_history(report, now),
            "letter": letter_to_dict(letter),
            "text": letter.text(),
            "dropped": dropped,
            "pages": pages,
        }
        self._store.save_letter(job_id, str(path), new, now)
        return path

    def resume(self, job_id: str) -> Resume:
        saved = self._store.resume(job_id)
        if saved is None:
            raise EditError("aucun CV généré")
        if "resume" not in saved[1]:
            raise EditError("CV généré avant l'édition : régénère-le pour le modifier")
        if self._candidate is None:
            raise EditError("profil candidat (candidate.json) introuvable")
        return resume_from_dict(saved[1]["resume"], self._candidate())

    def edit_resume(
        self,
        job_id: str,
        headline: str,
        summary: str,
        bullets: dict[str, str],
        now: datetime,
    ) -> Path:
        """`bullets` maps an item id to its bullets, one per line."""
        job = self._store.get_job(job_id)
        saved = self._store.resume(job_id)
        if job is None or saved is None:
            raise EditError("aucun CV généré")
        current = self.resume(job_id)
        assert self._candidate is not None  # checked by resume()

        def edited(pairs):
            result = []
            for item, old in pairs:
                text = bullets.get(item.id)
                lines = old if text is None else tuple(
                    line.strip(" -•\t") for line in _clean(text).splitlines()
                    if line.strip(" -•\t")
                )  # fmt: skip
                result.append((item, lines[:MAX_BULLETS]))
            return tuple(result)

        resume = replace(
            current,
            headline=_clean(headline)[:200],
            summary=_clean(summary) or current.summary,
            experiences=edited(current.experiences),
            projects=edited(current.projects),
            dropped=(),
        )
        convention = convention_for(job.location)
        scored = self._store.scored_job(job_id)
        visa = scored.assessment.work_authorisation if scored else "uncertain"
        data, dropped_chars, pages, removed = resume_pdf.render(
            resume, self._candidate(), self._contact, convention, visa
        )
        path = Path(saved[0])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        report = saved[1]
        new = {
            **report,
            **_history(report, now),
            "resume": resume_to_dict(resume),
            "dropped_chars": dropped_chars,
            "pages": pages,
            "fit_removed": removed,
        }
        self._store.save_resume(job_id, str(path), new, now)
        return path
