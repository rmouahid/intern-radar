from intern_radar.letters.checks import (
    blacklisted,
    keyword_coverage,
    unverified_tokens,
)


def test_keyword_coverage_is_case_insensitive_on_whole_terms():
    text = "I used python, FastAPI and C++ on a RAG pipeline."
    present, missing = keyword_coverage(text, ["Python", "C++", "RAG", "Go", "API"])
    assert present == ["Python", "C++", "RAG"]
    assert missing == ["Go", "API"]


def test_blacklisted_finds_cliches_and_em_dashes():
    text = "I am thrilled to apply — and eager to leverage my skills."
    assert blacklisted(text) == ["thrilled", "leverage", "—"]
    assert blacklisted("I built a RAG agent in Python.") == []


def test_unverified_tokens_flags_unknown_names_and_numbers():
    text = (
        "I built a RAG agent at SYSETELE. My work at Google improved latency "
        "by 40%. During 2027 I am available."
    )
    sources = ["RAG agent SYSETELE internship", "available March 2027"]
    assert unverified_tokens(text, sources) == ["Google", "40%"]


def test_sentence_initial_words_are_not_flagged():
    assert unverified_tokens("During my internship I learned a lot.", [""]) == []


def test_accented_proper_nouns_are_checked():
    assert unverified_tokens("I studied at the École Polytechnique.", ["x"]) == [
        "École",
        "Polytechnique",
    ]


def test_numbers_are_checked_with_the_following_word():
    text = "I worked at SYSETELE for 3 years."
    assert unverified_tokens(text, ["SYSETELE internship, 3 projects"]) == ["3 years"]
    assert unverified_tokens("I shipped 3 projects.", ["3 projects"]) == []
