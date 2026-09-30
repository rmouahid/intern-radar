"""Country conventions for CVs and cover letters.

Encodes the candidate's writing guide: paper size, length, spelling, date
style, section order and titles, work-status lines and local mentions differ
between the United States, the United Kingdom, Germany, the Nordics…
The region is detected from the offer's location; offers elsewhere use an
international (A4, British-leaning) default.
"""

import re
from dataclasses import dataclass
from datetime import date

from intern_radar.countries import mentions_any

# Section keys, rendered with localised titles.
SUMMARY, EDUCATION, SKILLS, EXPERIENCE, PROJECTS, CERTIFICATIONS, LANGUAGES = (
    "summary",
    "education",
    "skills",
    "experience",
    "projects",
    "certifications",
    "languages",
)


@dataclass(frozen=True)
class Convention:
    region: str
    paper: str  # "Letter" or "A4"
    cv_pages: int  # maximum pages for an internship CV
    spelling: str  # instruction for the LLM
    numeric_dates: bool  # "09/2024" instead of "Sep 2024"
    summary_title: str  # English title of the summary section
    sections: tuple[str, ...]
    tabular: bool = False  # dates in a left column (German-style Lebenslauf)
    work_status: bool = True  # print the right-to-work line
    nationality: bool = False  # print nationality (Switzerland, Gulf…)
    referees: bool = False  # "Referees available on request"
    gdpr_clause: str = ""  # consent clause required at the bottom of the CV
    letter_words: tuple[int, int] = (250, 400)
    letter_date: str = "uk"  # "us": September 30, 2026; "uk": 30 September 2026
    closing_unnamed: str = "Kind regards,"  # English closing, unnamed recipient
    notes: str = ""  # extra instruction for the LLM


EUROPE = (SUMMARY, EXPERIENCE, EDUCATION, SKILLS, PROJECTS, CERTIFICATIONS, LANGUAGES)
NORTH_AMERICA = (
    SUMMARY,
    EDUCATION,  # students: education before experience
    SKILLS,
    EXPERIENCE,
    PROJECTS,
    CERTIFICATIONS,
    LANGUAGES,
)
UK = (SUMMARY, SKILLS, EXPERIENCE, EDUCATION, PROJECTS, CERTIFICATIONS, LANGUAGES)
DACH = (EXPERIENCE, EDUCATION, SKILLS, LANGUAGES, CERTIFICATIONS, PROJECTS)

POLAND_CLAUSE = (
    "Wyrażam zgodę na przetwarzanie moich danych osobowych dla potrzeb "
    "niezbędnych do realizacji procesu rekrutacji (zgodnie z RODO)."
)
ITALY_CLAUSE = (
    "Autorizzo il trattamento dei miei dati personali presenti nel CV ai sensi "
    "del Decreto Legislativo 30 giugno 2003, n. 196 e del GDPR (Regolamento UE "
    "2016/679)."
)

CONVENTIONS: dict[str, Convention] = {
    "us": Convention(
        "United States", "Letter", 1, "American English", False, "Summary",
        NORTH_AMERICA, letter_date="us", closing_unnamed="Sincerely,",
        notes="No objective or hobbies section. Summary: 2 lines at most.",
    ),
    "canada": Convention(
        "Canada", "Letter", 1, "Canadian English (centre, colour, organization)",
        False, "Summary", NORTH_AMERICA, letter_date="us",
        closing_unnamed="Sincerely,",
        notes="Mention being bilingual English/French when relevant.",
    ),
    "quebec": Convention(
        "Québec", "Letter", 1, "French from Québec when written in French "
        "(courriel, logiciel), Canadian English otherwise", False, "Profile",
        NORTH_AMERICA, letter_date="uk", closing_unnamed="Sincerely,",
        notes="French is often expected: follow the offer's language.",
    ),
    "uk": Convention(
        "United Kingdom", "A4", 1, "British English (optimised, organisation, "
        "programme)", False, "Personal statement", UK,
        closing_unnamed="Yours faithfully,",
        notes="Personal statement of 3 to 4 lines. Avoid superlatives.",
    ),
    "ireland": Convention(
        "Ireland", "A4", 1, "British/Irish English", False, "Personal statement",
        UK, closing_unnamed="Yours faithfully,",
    ),
    "dach": Convention(
        "Germany/Austria/Switzerland", "A4", 2, "German when written in German "
        "(Switzerland: no ß), British English otherwise", True, "Profile", DACH,
        tabular=True, work_status=False, letter_date="de",
        closing_unnamed="Kind regards,",
        notes="Factual and structured; no gaps in the timeline.",
    ),
    "switzerland": Convention(
        "Switzerland", "A4", 2, "Swiss German (no ß) when written in German, "
        "British English otherwise", True, "Profile", DACH, tabular=True,
        work_status=False, nationality=True, letter_date="de",
        closing_unnamed="Kind regards,",
        notes="Measured, precise tone; mention national languages spoken.",
    ),
    "benelux": Convention(
        "Benelux", "A4", 1, "British English", False, "Profile", EUROPE,
        work_status=False, letter_words=(150, 300),
        notes="Direct, personal and short; honest, no exaggeration.",
    ),
    "nordics": Convention(
        "Nordic countries", "A4", 1, "British English", False, "Profile", EUROPE,
        work_status=False, letter_words=(150, 300),
        notes="Modest, warm tone; autonomy and collaboration; no big claims.",
    ),
    "norway": Convention(
        "Norway", "A4", 1, "British English", False, "Profile", EUROPE,
        work_status=False, referees=True, letter_words=(150, 300),
        notes="Modest, direct tone; flat culture.",
    ),
    "poland": Convention(
        "Poland", "A4", 1, "British English", False, "Profile", EUROPE,
        work_status=False, gdpr_clause=POLAND_CLAUSE,
    ),
    "italy": Convention(
        "Italy", "A4", 1, "British English", False, "Profile", EUROPE,
        work_status=False, gdpr_clause=ITALY_CLAUSE,
    ),
    "south_europe": Convention(
        "Southern/Eastern Europe", "A4", 1, "British English", False, "Profile",
        EUROPE, work_status=False,
    ),
    "australia": Convention(
        "Australia/New Zealand", "A4", 2, "Australian/British English "
        "(organisation, optimise)", False, "Summary", UK, referees=True,
        closing_unnamed="Yours sincerely,",
        notes="Cordial, direct, no self-aggrandising (tall poppy syndrome).",
    ),
    "singapore": Convention(
        "Singapore", "A4", 1, "British English", False, "Summary", UK,
        nationality=True, closing_unnamed="Yours sincerely,",
        notes="Certifications are valued.",
    ),
    "india": Convention(
        "India", "A4", 1, "British English", False, "Summary", NORTH_AMERICA,
        closing_unnamed="Yours sincerely,",
    ),
    "japan": Convention(
        "Japan (international companies)", "A4", 1, "American English", False,
        "Summary", NORTH_AMERICA, closing_unnamed="Sincerely,",
        notes="Respectful, formal tone and a precise motivation for the company.",
    ),
    "china": Convention(
        "China/Hong Kong/Taiwan", "A4", 1, "British English", False, "Summary",
        UK, nationality=True, closing_unnamed="Yours sincerely,",
        notes="Short, respectful letter.",
    ),
    "gulf": Convention(
        "Gulf states", "A4", 2, "British English", False, "Summary", UK,
        nationality=True, referees=True, closing_unnamed="Yours faithfully,",
        notes="Formal, respectful; nothing personal, religious or political.",
    ),
    "international": Convention(
        "International", "A4", 1, "British English", False, "Summary", UK,
    ),
}  # fmt: skip

# Checked in order: specific places before the countries that contain them.
REGION_COUNTRIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("quebec", ("Québec",)),
    ("canada", ("Canada",)),
    ("us", ("United States",)),
    ("uk", ("United Kingdom",)),
    ("ireland", ("Ireland",)),
    ("switzerland", ("Switzerland",)),
    ("dach", ("Germany", "Austria")),
    ("benelux", ("Netherlands", "Belgium", "Luxembourg")),
    ("norway", ("Norway",)),
    ("nordics", ("Sweden", "Denmark", "Finland", "Iceland")),
    ("poland", ("Poland",)),
    ("italy", ("Italy",)),
    ("south_europe", ("Spain", "Portugal", "Greece", "Czechia", "Romania",
                      "Hungary", "Bulgaria", "Croatia", "Estonia")),
    ("australia", ("Australia", "New Zealand")),
    ("singapore", ("Singapore",)),
    ("india", ("India",)),
    ("japan", ("Japan",)),
    ("china", ("China", "Hong Kong", "Taiwan")),
    ("gulf", ("United Arab Emirates", "Saudi Arabia", "Qatar")),
)  # fmt: skip
US_STATES = (
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO "
    "MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC"
).split()
US_RE = re.compile(
    rf"(?:^|[,;]\s*)US(?:A)?\b|,\s*(?:{'|'.join(US_STATES)})\s*(?:$|[,;])"
)


def convention_for(location: str) -> Convention:
    """The convention of the first region the offer's location names."""
    for region, countries in REGION_COUNTRIES:
        if mentions_any(location, countries):
            return CONVENTIONS[region]
    if US_RE.search(location.strip()):  # "US, CA, Santa Clara", "Austin, TX"
        return CONVENTIONS["us"]
    return CONVENTIONS["international"]


# --- localisation -------------------------------------------------------------

TITLES = {
    "en": {
        EDUCATION: "Education",
        SKILLS: "Skills",
        EXPERIENCE: "Experience",
        PROJECTS: "Projects",
        CERTIFICATIONS: "Certifications",
        LANGUAGES: "Languages",
    },
    "fr": {
        SUMMARY: "Profil",
        EDUCATION: "Formation",
        SKILLS: "Compétences techniques",
        EXPERIENCE: "Expérience professionnelle",
        PROJECTS: "Projets",
        CERTIFICATIONS: "Certifications",
        LANGUAGES: "Langues",
    },
    "de": {
        SUMMARY: "Profil",
        EDUCATION: "Ausbildung",
        SKILLS: "Kenntnisse",
        EXPERIENCE: "Berufserfahrung",
        PROJECTS: "Projekte",
        CERTIFICATIONS: "Weiterbildung und Zertifikate",
        LANGUAGES: "Sprachen",
    },
}


def section_title(convention: Convention, key: str, language: str) -> str:
    titles = TITLES.get(language, TITLES["en"])
    if key == SUMMARY and language not in ("fr", "de"):
        return convention.summary_title
    return titles.get(key) or TITLES["en"][key]


MONTHS = {
    "jan": 1, "janv": 1, "january": 1, "janvier": 1, "januar": 1, "jänner": 1,
    "feb": 2, "fév": 2, "févr": 2, "february": 2, "février": 2, "februar": 2,
    "mar": 3, "march": 3, "mars": 3, "märz": 3,
    "apr": 4, "avr": 4, "april": 4, "avril": 4,
    "may": 5, "mai": 5,
    "jun": 6, "june": 6, "juin": 6, "juni": 6,
    "jul": 7, "july": 7, "juil": 7, "juillet": 7, "juli": 7,
    "aug": 8, "august": 8, "août": 8, "aout": 8,
    "sep": 9, "sept": 9, "september": 9, "septembre": 9,
    "oct": 10, "october": 10, "octobre": 10, "okt": 10, "oktober": 10,
    "nov": 11, "november": 11, "novembre": 11,
    "dec": 12, "déc": 12, "december": 12, "décembre": 12, "dez": 12, "dezember": 12,
}  # fmt: skip
EN_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
PRESENT = {
    "en": "Present",
    "fr": "aujourd'hui",
    "de": "heute",
}
PRESENT_RE = re.compile(
    r"\b(present|ongoing|current|now|aujourd'hui|en cours|heute)\b", re.I
)
DATE_RE = re.compile(r"(?:([A-Za-zÀ-ÿ]+)\.?\s+)?((?:19|20)\d\d)")


def format_dates(text: str, convention: Convention, language: str = "en") -> str:
    """Dates of a range in one consistent style ("Sep 2024 – Present").

    Unrecognised text is returned unchanged, so nothing is ever lost.
    """
    points = []
    for month_word, year in DATE_RE.findall(text):
        month = MONTHS.get(month_word.lower().rstrip(".")) if month_word else None
        if convention.numeric_dates or language in ("fr", "de"):
            points.append(f"{month:02d}/{year}" if month else year)
        else:
            points.append(f"{EN_MONTHS[month - 1]} {year}" if month else year)
    if not points:
        return text.strip()
    if PRESENT_RE.search(text) and len(points) == 1:
        points.append(PRESENT.get(language, PRESENT["en"]))
    return " – ".join(points[:2])


def recency(dates: str) -> tuple[int, int]:
    """Sort key, most recent first: (end year, start year); ongoing = latest."""
    years = [int(y) for _, y in DATE_RE.findall(dates)]
    end = 9999 if PRESENT_RE.search(dates) else max(years, default=0)
    return (-end, -min(years, default=0))


def work_status_line(convention: Convention, work_authorisation: str) -> str:
    """Right-to-work line for the CV header, or "" when not customary."""
    if convention.nationality:
        if work_authorisation == "free":
            return "Nationality: French (EU/EFTA, no work permit required)"
        return "Nationality: French"
    if not convention.work_status:
        return ""
    return {
        "free": "EU citizen: no work permit required",
        "self_arranged": "Eligible for a Working Holiday visa: no sponsorship required",
    }.get(work_authorisation, "French citizen: requires visa sponsorship")


# --- cover letters -------------------------------------------------------------

FRENCH_MONTHS = (
    "janvier février mars avril mai juin juillet août septembre octobre "
    "novembre décembre"
).split()


def letter_formulas(convention: Convention, language: str) -> tuple[str, str]:
    """Salutation and closing for an unnamed recipient, by language and region."""
    if language == "fr":
        return (
            "Madame, Monsieur,",
            "Veuillez agréer, Madame, Monsieur, l'expression de mes salutations "
            "distinguées.",
        )
    if language == "de":
        swiss = convention is CONVENTIONS["switzerland"]
        return (
            "Sehr geehrte Damen und Herren,",
            "Mit freundlichen Grüssen" if swiss else "Mit freundlichen Grüßen",
        )
    if language == "es":
        return "Estimados señores:", "Atentamente,"
    return "Dear Hiring Manager,", convention.closing_unnamed


def letter_date(convention: Convention, language: str, day: date) -> str:
    if language == "fr":
        return f"{day.day} {FRENCH_MONTHS[day.month - 1]} {day.year}"
    if language == "de":
        return f"{day:%d.%m.%Y}"
    if convention.letter_date == "us":
        return f"{day:%B} {day.day}, {day.year}"
    return f"{day.day} {day:%B} {day.year}"


def letter_subject(language: str, title: str) -> str:
    return {
        "fr": f"Objet : candidature au poste de {title}",
        "de": f"Bewerbung als {title}",
        "es": f"Asunto: candidatura para {title}",
    }.get(language, f"Application for {title}")


def visa_fact(work_authorisation: str) -> str:
    """Right-to-work fact for the letter; "" in the EU/EEA/Switzerland."""
    return {
        "free": "",
        "self_arranged": "The candidate can obtain a Working Holiday visa "
        "without any employer sponsorship.",
        "programme": "The candidate would need the standard intern visa "
        "programme for this country.",
    }.get(work_authorisation, "The candidate would need visa sponsorship.")
