"""Answers to application forms: a bank of standard answers, plus answers
computed from the offer (work authorisation, sponsorship, relocation, dates).

Standard answers have defaults built from the profile and the structured
candidate profile until the candidate validates their own text. Offer answers
are never invented: they follow the offer's work authorisation, set by rules
for the EU/EEA/Switzerland and working-holiday countries.
"""

import re
from dataclasses import dataclass
from datetime import date

from intern_radar.candidate import Candidate
from intern_radar.config import Profile

CUSTOM_PREFIX = "custom:"


@dataclass(frozen=True)
class Field:
    key: str
    label: str  # French label in the app
    question: str  # how forms usually ask it (English)


STANDARD: tuple[Field, ...] = (
    Field("full_name", "Nom complet", "Full name"),
    Field("email", "E-mail", "Email"),
    Field("phone", "Téléphone", "Phone"),
    Field("location", "Adresse / ville", "Current location"),
    Field("linkedin", "LinkedIn", "LinkedIn profile"),
    Field("github", "GitHub / site", "Website, GitHub or portfolio"),
    Field("school", "École", "School / University"),
    Field("degree", "Diplôme", "Degree and field of study"),
    Field("graduation", "Fin des études", "Expected graduation date"),
    Field("availability", "Disponibilités", "When can you start, and for how long?"),
    Field("languages", "Langues", "Languages spoken"),
    Field(
        "heard_from", "Comment avez-vous connu l'offre", "How did you hear about us?"
    ),
    Field("salary", "Rémunération souhaitée", "Salary expectations"),
)
BY_KEY = {f.key: f for f in STANDARD}


@dataclass(frozen=True)
class Answer:
    key: str
    label: str
    question: str
    value: str
    validated: bool  # saved by the candidate (otherwise a proposed default)


def _graduation(dates: str) -> str:
    """'Sept. 2024 – Sept. 2028' -> 'Sept. 2028'."""
    parts = re.split(r"\s*[–-]\s*", dates.strip())
    return parts[-1] if parts and re.search(r"\d{4}", parts[-1]) else dates


def _period(profile: Profile) -> str:
    return (
        f"Available for a 6-month internship from {_day(profile.window_start)} "
        f"to {_day(profile.window_end)} (minimum {profile.min_months} months)."
    )


def _day(day: date) -> str:
    return f"{day.day} {day:%B %Y}"


def defaults(profile: Profile, candidate: Candidate | None) -> dict[str, str]:
    """Proposed answers, from profile.yaml and candidate.json."""
    values = {key: "" for key in BY_KEY}
    contact = profile.contact
    if contact is not None:
        values |= {
            "full_name": contact.name,
            "email": contact.email,
            "phone": contact.phone,
            "location": contact.location,
            "linkedin": contact.linkedin,
            "github": contact.github,
        }
    if candidate is not None and candidate.education:
        current = candidate.education[0]
        values |= {
            "school": current.school,
            "degree": current.degree,
            "graduation": _graduation(current.dates),
        }
    if candidate is not None and candidate.languages:
        values["languages"] = ", ".join(
            f"{x.language} ({x.level})" for x in candidate.languages
        )
    values["availability"] = _period(profile)
    values["heard_from"] = "Company careers page"
    values["salary"] = "Open — in line with your standard internship compensation."
    return values


def merged(
    saved: dict[str, tuple[str, str]],
    profile: Profile,
    candidate: Candidate | None,
) -> list[Answer]:
    """Standard answers (saved text, else the default), then custom ones.

    `saved` maps a key to (question, value), as the store returns them.
    """
    proposed = defaults(profile, candidate)
    answers = [
        Answer(
            f.key,
            f.label,
            f.question,
            saved[f.key][1] if f.key in saved else proposed[f.key],
            f.key in saved,
        )
        for f in STANDARD
    ]
    answers += [
        Answer(key, question, question, value, True)
        for key, (question, value) in sorted(saved.items())
        if key.startswith(CUSTOM_PREFIX)
    ]
    return answers


WORK_AUTHORISATION = {
    "en": {
        "free": (
            "Yes. I am a French (EU) citizen: no work permit is required.",
            "No.",
        ),
        "self_arranged": (
            "Yes, with a Working Holiday visa that I obtain myself.",
            "No, I do not need employer sponsorship.",
        ),
        "programme": (
            "Not yet: I would need the standard intern visa for this country.",
            "Yes: an intern visa (e.g. J-1), usually arranged through an exchange "
            "programme sponsor.",
        ),
        None: (
            "Not yet: I would need a work visa for this internship.",
            "Yes, I would need visa sponsorship.",
        ),
    },
    "fr": {
        "free": (
            "Oui. Je suis citoyen français (UE) : aucun permis de travail requis.",
            "Non.",
        ),
        "self_arranged": (
            "Oui, avec un visa vacances-travail que j'obtiens moi-même.",
            "Non, je n'ai pas besoin d'un parrainage de l'employeur.",
        ),
        "programme": (
            "Pas encore : il me faudrait le visa stagiaire standard de ce pays.",
            "Oui : un visa stagiaire (par ex. J-1), généralement obtenu via un "
            "programme d'échange.",
        ),
        None: (
            "Pas encore : il me faudrait un visa de travail pour ce stage.",
            "Oui, il me faudrait un parrainage de visa.",
        ),
    },
}
QUESTIONS = {
    "en": (
        "Are you legally authorised to work in this country?",
        "Will you now or in the future require visa sponsorship?",
        "Are you willing to relocate?",
        "Earliest start date",
        "Internship duration",
    ),
    "fr": (
        "Êtes-vous autorisé à travailler dans ce pays ?",
        "Aurez-vous besoin d'un parrainage de visa ?",
        "Êtes-vous prêt à déménager ?",
        "Date de début au plus tôt",
        "Durée du stage",
    ),
}
FRENCH_MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
    "septembre", "octobre", "novembre", "décembre",
)  # fmt: skip


def _localised_day(day: date, language: str) -> str:
    if language == "fr":
        return f"{day.day} {FRENCH_MONTHS[day.month - 1]} {day.year}"
    return _day(day)


def offer_answers(
    work_authorisation: str, location: str, profile: Profile, language: str = "en"
) -> list[tuple[str, str]]:
    """Answers that depend on the offer, as (question, answer), in English
    or French."""
    language = language if language in QUESTIONS else "en"
    table = WORK_AUTHORISATION[language]
    authorised, sponsorship = table.get(work_authorisation, table[None])
    place = location.split(";")[0].strip()
    start = _localised_day(profile.window_start, language)
    end = _localised_day(profile.window_end, language)
    if language == "fr":
        relocate = f"Oui, je suis prêt à m'installer à {place or 'ce poste'}."
        duration = (
            f"6 mois, jusqu'au {end} au plus tard (minimum {profile.min_months} mois)."
        )
    else:
        relocate = f"Yes, I am willing to relocate to {place or 'the job location'}."
        duration = (
            f"6 months, until {end} at the latest "
            f"(minimum {profile.min_months} months)."
        )
    return list(
        zip(
            QUESTIONS[language],
            (authorised, sponsorship, relocate, start, duration),
            strict=True,
        )
    )
