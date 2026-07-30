"""Skills dictionary and detector: alias mapping, boundary safety (no short
token hitting inside a word), single-letter languages, ordering, and size,
plus the two-tier gate that keeps ambiguous English-word skills honest."""

import pytest

from app import skills as skills_module
from app.skills import (
    _AMBIGUOUS_ALIASES,
    ALIAS_TO_CANONICAL,
    SKILLS,
    find_skills,
)


def test_dictionary_is_large_and_curated():
    # The plan asks for roughly 200-250 canonical skills.
    assert len(SKILLS) >= 200
    assert len(ALIAS_TO_CANONICAL) > len(SKILLS)


def test_no_alias_maps_to_two_canonicals():
    # _build_alias_map raises on a collision, so importing already proves this;
    # this asserts the invariant explicitly for future edits.
    seen: dict[str, str] = {}
    for canonical, aliases in SKILLS.items():
        for alias in aliases:
            key = alias.lower()
            assert key not in seen or seen[key] == canonical, (
                f"{alias!r} maps to {seen.get(key)!r} and {canonical!r}"
            )
            seen[key] = canonical


def test_build_alias_map_raises_on_duplicate_alias(monkeypatch):
    # An injected duplicate alias across two canonicals must be rejected.
    monkeypatch.setattr(
        skills_module, "SKILLS", {"Foo": ["shared"], "Bar": ["shared"]}
    )
    with pytest.raises(ValueError):
        skills_module._build_alias_map()


def test_ambiguous_aliases_all_exist_in_the_dictionary():
    # Every gated alias must be a real alias, or the gate silently does nothing.
    assert _AMBIGUOUS_ALIASES <= set(ALIAS_TO_CANONICAL)


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("k8s", "Kubernetes"),
        ("kubernetes", "Kubernetes"),
        ("js", "JavaScript"),
        ("javascript", "JavaScript"),
        ("ts", "TypeScript"),
        ("typescript", "TypeScript"),
        ("gcp", "Google Cloud"),
        ("google cloud", "Google Cloud"),
        ("ci/cd", "CI/CD"),
        ("postgres", "PostgreSQL"),
        ("postgresql", "PostgreSQL"),
        ("golang", "Go"),
    ],
)
def test_required_alias_mappings(alias, canonical):
    assert ALIAS_TO_CANONICAL[alias] == canonical
    assert find_skills(f"experience with {alias} required") == [canonical]


def test_aliases_and_canonical_collapse_to_one():
    found = find_skills("We use Kubernetes (k8s) and JS / JavaScript daily")
    assert found == ["Kubernetes", "JavaScript"]


def test_case_insensitive():
    assert find_skills("PYTHON and Python and python") == ["Python"]


@pytest.mark.parametrize(
    "text",
    [
        "improve the structure of your code",  # no bare "r"
        "google, category, cargo, and goose",  # no "go" inside words
        "he played soccer for the abc club",  # no "c" inside words
        "the arts and crafts fair",  # no "ts" inside "arts"
        "spinning up an instance",  # no false skill at all
    ],
)
def test_no_false_positive_inside_words(text):
    # Short tokens that ARE skills on their own must never fire when they are
    # only ever glued inside a larger word.
    assert find_skills(text) == []


def test_java_not_detected_inside_javascript():
    # "java" must not be pulled out of "javascript"; only JavaScript is found.
    assert find_skills("senior javascript developer") == ["JavaScript"]


def test_single_letter_languages_when_standalone():
    found = find_skills("Languages: C, R, and Go. Also C++ and C#.")
    assert "C" in found
    assert "R" in found
    assert "Go" in found
    assert "C++" in found
    assert "C#" in found


def test_c_family_do_not_bleed_into_each_other():
    assert find_skills("c++") == ["C++"]
    assert find_skills("c#") == ["C#"]
    # A lone "c" is C, not C++ or C#.
    assert find_skills("proficient in c.") == ["C"]


def test_longest_alias_wins():
    # "google cloud platform" must win over the bare "gcp"/"google cloud".
    assert find_skills("on google cloud platform") == ["Google Cloud"]
    # "node.js" is consumed whole rather than also yielding JavaScript from "js".
    assert find_skills("built on Node.js") == ["Node.js"]


def test_first_occurrence_order_and_dedupe():
    text = "Docker, then Python, then Docker again, then Kubernetes"
    assert find_skills(text) == ["Docker", "Python", "Kubernetes"]


def test_multiword_survives_line_wrap():
    assert find_skills("strong machine\nlearning background") == ["Machine Learning"]


def test_empty_and_none_return_empty_list():
    assert find_skills("") == []
    assert find_skills(None) == []
    assert find_skills("just some ordinary prose with no tech in it") == []


# ---------------------------------------------------------------------------
# Two-tier gate: ambiguous English-word skills must not fire on plain prose,
# but must still match in a genuine technical context.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prose",
    [
        "can go the extra mile and go above and beyond",
        "a go-to person; go-live is next week",
        "Heavy R&D investment",
        "at the C-suite / C-level",
        "Washington D.C.",
        "starting spring 2026",
        "we reject the notion that",
        "sketch out ideas",
        "swift decision-making",
        "candidates who spark innovation",
        "at the helm of major initiatives",
        "we value guard rails",
        "a confluence of design and engineering",
        "you will eclipse the competition",
    ],
)
def test_ambiguous_terms_dropped_in_plain_english(prose):
    assert find_skills(prose) == []


def test_lambda_alone_is_not_aws_lambda():
    # "lambda functions" in a Python context is the language feature, not AWS.
    assert find_skills("we use lambda functions extensively in Python") == ["Python"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Go developer", ["Go"]),
        ("experience with Go and Rust", ["Go", "Rust"]),
        ("R and Python for data", ["R", "Python"]),
        ("Spring Boot microservices", ["Spring"]),
        ("Apache Spark / PySpark", ["Apache Spark"]),
        ("Ruby on Rails", ["Ruby on Rails"]),
        ("Helm charts on Kubernetes", ["Helm", "Kubernetes"]),
        ("SwiftUI for iOS", ["SwiftUI", "iOS"]),
        ("C/C++/C# on the backend", ["C", "C++", "C#"]),
        ("Skills: Go, React, AWS", ["Go", "React", "AWS"]),
    ],
)
def test_ambiguous_terms_kept_in_tech_context(text, expected):
    found = find_skills(text)
    for skill in expected:
        assert skill in found, f"{skill!r} missing from {found!r} for {text!r}"


def test_confirmation_propagates_across_a_conjunction():
    # "experience" confirms Go; Go then confirms the adjacent Rust.
    assert find_skills("experience with Go and Rust") == ["Go", "Rust"]


def test_ambiguous_hit_confirmed_by_a_delimited_skills_list():
    # A long comma list reaches past the token window, but the run holds
    # confirmed skills (Python, Java, ...), so Go is rescued by signal (c).
    text = "Java, Python, Ruby, PHP, Scala, Kotlin, Go"
    assert "Go" in find_skills(text)


# ---------------------------------------------------------------------------
# Sentence/line barriers: the disambiguation window must NOT cross a sentence
# or newline, so real multi-sentence job posts do not list phantom skills.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "jd",
    [
        "You must go the extra mile and thrive this spring.",
        "Python developer. go the extra mile.",
        "We use Python and Docker. Go-live is next week.",
        "Required: Python, FastAPI. You must go the extra mile.",
        "Django and Python experience. This spring we ship fast.",
    ],
)
def test_no_phantom_ambiguous_across_sentence_break(jd):
    found = find_skills(jd)
    assert "Go" not in found
    assert "Spring" not in found


def test_realistic_jd_has_the_real_skills_and_no_phantoms():
    jd = (
        "Backend Engineer. Required: Python, FastAPI, PostgreSQL, Kubernetes, "
        "AWS, CI/CD. Nice to have: Redis, GraphQL, Docker. You must go the "
        "extra mile and thrive this spring."
    )
    found = find_skills(jd)
    for skill in (
        "Python", "FastAPI", "PostgreSQL", "Kubernetes", "AWS", "CI/CD",
        "Redis", "GraphQL", "Docker",
    ):
        assert skill in found, f"{skill} missing from {found}"
    # The ordinary words in the closing sentence must not become skills.
    assert "Go" not in found
    assert "Spring" not in found


def test_newline_separates_sentences_for_gating():
    # A skill on one line does not vouch for an ambiguous word on the next.
    assert find_skills("Python developer\ngo the extra mile") == ["Python"]


def test_ambiguous_kept_when_signal_shares_the_sentence():
    # The mirror of the barrier tests: same-sentence signals still confirm.
    assert "Go" in find_skills("Go developer with Python experience")
    assert "R" in find_skills("R and Python for data science")
    assert "Go" in find_skills("Skills: Go, React, AWS, Docker")
