"""Server-derived usernames: slugging, collisions, odd emails and names."""

import pytest

from app.identity import derive_username, slugify_username
from app.models import User


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Haris", "haris"),
        ("haris.jamal", "haris_jamal"),
        ("HARIS+jobs", "haris_jobs"),
        ("a--b", "a_b"),
        ("Jose Muller", "jose_muller"),
        ("  spaced  out  ", "spaced_out"),
        ("!!!", ""),
        ("", ""),
    ],
)
def test_slugify_username(raw, expected):
    assert slugify_username(raw) == expected


def test_slugify_transliterates_non_ascii():
    # Accented Latin folds to ASCII; CJK has no ASCII form and drops out.
    assert slugify_username("Jose") == "jose"
    assert slugify_username("Zoe") == "zoe"
    assert slugify_username("Ali Reza") == "ali_reza"


@pytest.fixture
async def session(asgi_app):
    async with asgi_app.state.sessionmaker() as db_session:
        yield db_session


async def _add_user(session, username: str, email: str | None = None) -> User:
    user = User(username=username, display_name=username, password_hash="x", email=email)
    session.add(user)
    await session.commit()
    return user


async def test_derives_from_email_local_part(session):
    assert await derive_username(session, "haris@example.com", "Haris Jamal") == "haris"


async def test_falls_back_to_display_name(session):
    # No email at all: the display name carries the handle.
    assert await derive_username(session, None, "Haris Jamal") == "haris_jamal"


async def test_collisions_get_numeric_suffixes(session):
    await _add_user(session, "haris")
    assert await derive_username(session, "haris@other.example", "Haris") == "haris2"
    await _add_user(session, "haris2")
    assert await derive_username(session, "haris@third.example", "Haris") == "haris3"


async def test_short_local_part_is_padded(session):
    handle = await derive_username(session, "jo@example.com", "")
    assert handle == "jo_user"
    assert len(handle) >= 3


async def test_unusable_email_and_name_still_yields_a_handle(session):
    handle = await derive_username(session, "!!!@example.com", "!!!")
    assert len(handle) >= 3
    assert handle.replace("_", "").isalnum()


async def test_long_local_part_is_truncated_to_30(session):
    handle = await derive_username(session, "x" * 60 + "@example.com", "Long")
    assert len(handle) <= 30


async def test_long_handle_collision_stays_within_30(session):
    long_email = "y" * 40 + "@example.com"
    first = await derive_username(session, long_email, "Long")
    await _add_user(session, first)
    second = await derive_username(session, long_email, "Long")
    assert second != first
    assert len(second) <= 30


async def test_non_ascii_display_name_with_no_email(session):
    handle = await derive_username(session, None, "Ali Reza")
    assert handle == "ali_reza"
