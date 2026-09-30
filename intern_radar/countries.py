"""Recognise countries in free-text job locations.

Used for the countries where the candidate can obtain work authorisation
without employer sponsorship (e.g. working holiday agreements). Locations
come in many shapes ("Toronto, Ontario, CAN", "Tokyo, JPN", "Sydney NSW"),
so each country is matched by its name, its ISO-3 code (upper case only)
and its main cities or regions. Two-letter codes are never used: "CA" is
California as often as Canada.
"""

import re

ALIASES: dict[str, tuple[str, ...]] = {
    "Canada": (
        "canada",
        "toronto",
        "montreal",
        "montréal",
        "vancouver",
        "ottawa",
        "calgary",
        "waterloo",
        "ontario",
        "quebec",
        "québec",
        "british columbia",
        "alberta",
    ),
    "Australia": (
        "australia",
        "sydney",
        "melbourne",
        "brisbane",
        "perth",
        "canberra",
        "new south wales",
    ),
    "New Zealand": ("new zealand", "auckland", "wellington", "christchurch"),
    "Japan": ("japan", "tokyo", "osaka", "kyoto", "yokohama", "fukuoka"),
    "South Korea": ("south korea", "korea", "seoul", "busan", "pangyo"),
    "Hong Kong": ("hong kong",),
    "Taiwan": ("taiwan", "taipei", "hsinchu"),
    "Argentina": ("argentina", "buenos aires"),
    "Chile": ("chile", "santiago de chile"),
    "Mexico": ("mexico", "méxico", "mexico city", "guadalajara", "monterrey"),
    "Brazil": ("brazil", "brasil", "são paulo", "sao paulo", "rio de janeiro"),
    "Colombia": ("colombia", "bogotá", "bogota", "medellín", "medellin"),
    "Uruguay": ("uruguay", "montevideo"),
    "Peru": ("peru", "perú", "lima"),
    "Ecuador": ("ecuador", "quito"),
    "Singapore": ("singapore",),
    "United Kingdom": ("united kingdom", "england", "london", "scotland", "uk"),
    "United States": ("united states", "usa", "new york", "san francisco"),
}
ISO3 = {
    "Canada": "CAN", "Australia": "AUS", "New Zealand": "NZL", "Japan": "JPN",
    "South Korea": "KOR", "Hong Kong": "HKG", "Taiwan": "TWN", "Argentina": "ARG",
    "Chile": "CHL", "Mexico": "MEX", "Brazil": "BRA", "Colombia": "COL",
    "Uruguay": "URY", "Peru": "PER", "Ecuador": "ECU", "Singapore": "SGP",
    "United Kingdom": "GBR", "United States": "USA",
}  # fmt: skip


# EU, EEA and Switzerland: a French citizen needs no work permit there.
FREE_MOVEMENT = (
    "Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia", "Denmark",
    "Estonia", "Finland", "Germany", "Greece", "Hungary", "Ireland", "Italy",
    "Latvia", "Lithuania", "Luxembourg", "Malta", "Netherlands", "Poland",
    "Portugal", "Romania", "Slovakia", "Slovenia", "Spain", "Sweden", "Iceland",
    "Liechtenstein", "Norway", "Switzerland",
)  # fmt: skip
ALIASES.update(
    {
        "Austria": ("austria", "vienna", "wien", "graz"),
        "Belgium": ("belgium", "brussels", "bruxelles", "antwerp", "ghent"),
        "Czechia": ("czechia", "czech republic", "prague", "brno"),
        "Denmark": ("denmark", "copenhagen", "aarhus"),
        "Finland": ("finland", "helsinki", "espoo"),
        "Germany": (
            "germany", "deutschland", "berlin", "munich", "münchen", "hamburg",
            "frankfurt", "stuttgart", "cologne", "köln", "düsseldorf", "manching",
            "bremen", "ottobrunn", "hesse", "bavaria", "bayern",
        ),
        "Greece": ("greece", "athens", "thessaloniki"),
        "Ireland": ("ireland", "dublin", "cork", "leixlip"),
        "Italy": ("italy", "italia", "milan", "milano", "rome", "roma", "turin"),
        "Netherlands": (
            "netherlands", "amsterdam", "rotterdam", "eindhoven", "the hague",
            "utrecht", "delft",
        ),
        "Poland": ("poland", "warsaw", "kraków", "krakow", "wroclaw", "gdansk"),
        "Portugal": ("portugal", "lisbon", "lisboa", "porto"),
        "Spain": ("spain", "españa", "madrid", "barcelona", "valencia", "seville"),
        "Sweden": ("sweden", "stockholm", "gothenburg", "malmö", "lund"),
        "Norway": ("norway", "oslo"),
        "Switzerland": (
            "switzerland", "zurich", "zürich", "geneva", "genève", "lausanne",
            "basel", "bern",
        ),
    }
)  # fmt: skip
ISO3.update(
    {
        "Austria": "AUT", "Belgium": "BEL", "Czechia": "CZE", "Denmark": "DNK",
        "Finland": "FIN", "Germany": "DEU", "Greece": "GRC", "Ireland": "IRL",
        "Italy": "ITA", "Netherlands": "NLD", "Poland": "POL", "Portugal": "PRT",
        "Spain": "ESP", "Sweden": "SWE", "Norway": "NOR", "Switzerland": "CHE",
    }
)  # fmt: skip


def _pattern(country: str) -> re.Pattern[str]:
    names = "|".join(re.escape(a) for a in ALIASES.get(country, (country.lower(),)))
    code = ISO3.get(country)
    upper = rf"|(?-i:\b{code}\b)" if code else ""
    return re.compile(rf"(?i:\b(?:{names})\b){upper}")


def mentions_any(location: str, countries: tuple[str, ...]) -> bool:
    """True when the location names one of `countries`."""
    return any(_pattern(country).search(location) for country in countries)


# Other countries used to detect the CV and letter conventions of an offer.
ALIASES.update(
    {
        "United States": (
            "united states", "usa", "u.s.", "new york", "san francisco", "seattle",
            "boston", "austin", "chicago", "mountain view", "menlo park",
            "palo alto", "santa clara", "sunnyvale", "cupertino", "san jose",
            "redmond", "los angeles", "washington", "california", "texas",
            "massachusetts", "pittsburgh", "atlanta", "denver", "miami",
        ),
        "Québec": ("québec", "quebec", "montréal", "montreal", "laval"),
        "Ireland": ("ireland", "dublin", "cork", "galway", "leixlip"),
        "Luxembourg": ("luxembourg",),
        "Iceland": ("iceland", "reykjavik"),
        "India": ("india", "bangalore", "bengaluru", "hyderabad", "pune", "mumbai",
                  "delhi", "chennai", "gurgaon", "noida"),
        "China": ("china", "beijing", "shanghai", "shenzhen", "hangzhou"),
        "United Arab Emirates": ("united arab emirates", "uae", "dubai", "abu dhabi"),
        "Saudi Arabia": ("saudi arabia", "riyadh", "jeddah"),
        "Qatar": ("qatar", "doha"),
        "Romania": ("romania", "bucharest", "cluj"),
        "Hungary": ("hungary", "budapest"),
        "Bulgaria": ("bulgaria", "sofia"),
        "Croatia": ("croatia", "zagreb"),
        "Estonia": ("estonia", "tallinn"),
    }
)  # fmt: skip
ISO3.update(
    {
        "United States": "USA", "Ireland": "IRL", "Luxembourg": "LUX", "India": "IND",
        "China": "CHN", "United Arab Emirates": "ARE", "Saudi Arabia": "SAU",
        "Qatar": "QAT", "Romania": "ROU", "Hungary": "HUN", "Bulgaria": "BGR",
    }
)  # fmt: skip
