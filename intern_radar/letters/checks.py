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
TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)*%?|[^\W\d_][\w+#.-]*[\w+#]|[^\W\d_]")
YEAR_RE = re.compile(r"(19|20)\d\d")
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
    """Proper nouns and numbers of `text` found in none of `sources`.

    A number is checked together with the word that follows it ("3 years"),
    so a "3" elsewhere in the CV does not vouch for it; years stand alone.
    """
    haystack = " ".join(sources)
    flagged: list[str] = []
    for sentence in SENTENCE_RE.split(text):
        words = TOKEN_RE.findall(sentence)
        for index, word in enumerate(words):
            if word[0].isdigit():
                following = words[index + 1] if index + 1 < len(words) else ""
                if (
                    following
                    and not following[0].isdigit()
                    and not YEAR_RE.fullmatch(word)
                ):
                    candidate = f"{word} {following}"
                else:
                    candidate = word
            elif (
                len(word) > 1
                and word[0].isupper()
                and (index > 0 or any(c.isupper() for c in word[1:]))
            ):
                candidate = word
            else:
                continue
            if candidate not in flagged and not _contains(haystack, candidate):
                flagged.append(candidate)
    return flagged
