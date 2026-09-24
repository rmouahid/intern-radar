"""Pure checks applied to generated cover letters."""

import re

# Phrases that make a letter read as generic or machine-written.
BLACKLIST: tuple[str, ...] = (
    "thrilled",
    "passionate about",
    "leverage",
    "leveraging",
    "fast-paced",
    "delve",
    "cutting-edge",
    "in today's",
    "excited to apply",
    "synergy",
    "tapestry",
    "embark",
    "testament to",
    "unwavering",
    "seamless",
    "—",
)
TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)*%?|[A-Za-z][\w+#.-]*[\w+#]|[A-Za-z]")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _contains(text: str, phrase: str) -> bool:
    pattern = rf"(?<!\w){re.escape(phrase)}(?!\w)"
    return re.search(pattern, text, re.IGNORECASE) is not None


def keyword_coverage(text: str, keywords: list[str]) -> tuple[list[str], list[str]]:
    present = [k for k in keywords if _contains(text, k)]
    missing = [k for k in keywords if not _contains(text, k)]
    return present, missing


def blacklisted(text: str) -> list[str]:
    return [
        phrase
        for phrase in BLACKLIST
        if (phrase in text if not phrase[0].isalnum() else _contains(text, phrase))
    ]


def unverified_tokens(text: str, sources: list[str]) -> list[str]:
    """Proper nouns and numbers of `text` found in none of `sources`."""
    haystack = " ".join(sources)
    flagged: list[str] = []
    for sentence in SENTENCE_RE.split(text):
        for index, word in enumerate(TOKEN_RE.findall(sentence)):
            is_number = word[0].isdigit()
            is_proper = (
                len(word) > 1
                and word[0].isupper()
                and (index > 0 or any(c.isupper() for c in word[1:]))
            )
            if (is_number or is_proper) and word not in flagged:
                if not _contains(haystack, word):
                    flagged.append(word)
    return flagged
