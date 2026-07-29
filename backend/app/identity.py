"""Server-side username derivation. Users never choose a handle."""

import re
import secrets
import unicodedata

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import User

USERNAME_MIN = 3
USERNAME_MAX = 30
_ALLOWED_RE = re.compile(r"[^a-z0-9_]+")


def slugify_username(raw: str) -> str:
    """Reduce arbitrary text to the [a-z0-9_] handle alphabet.

    Non-ASCII is transliterated where possible (Jose -> jose); anything left
    over becomes an underscore. Returns "" when nothing usable remains.
    """
    decomposed = unicodedata.normalize("NFKD", raw or "")
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii")
    slug = _ALLOWED_RE.sub("_", ascii_text.strip().lower()).strip("_")
    slug = re.sub(r"_{2,}", "_", slug)
    return slug[:USERNAME_MAX]


def _candidate_base(email: str | None, display_name: str | None) -> str:
    """Prefer the email local part, then the display name, then a random handle."""
    if email and "@" in email:
        base = slugify_username(email.split("@", 1)[0])
        if len(base) >= USERNAME_MIN:
            return base
    else:
        base = ""
    from_display = slugify_username(display_name or "")
    if len(from_display) >= USERNAME_MIN:
        return from_display
    # Pad a too-short but real base (e.g. "jo") rather than discarding it.
    for short in (base, from_display):
        if short:
            return (short + "_user")[:USERNAME_MAX]
    return "user_" + secrets.token_hex(3)


async def derive_username(
    session: AsyncSession, email: str | None, display_name: str | None
) -> str:
    """A unique handle derived from the email local part or the display name.

    Collisions get a numeric suffix (haris, haris2, haris3, ...); after many
    collisions a random suffix keeps it short and still unique.
    """
    base = _candidate_base(email, display_name)
    candidate = base
    suffix = 1
    while await session.scalar(select(User.id).where(User.username == candidate)):
        suffix += 1
        if suffix > 50:
            candidate = f"{base[:USERNAME_MAX - 7]}_{secrets.token_hex(3)}"
            continue
        tail = str(suffix)
        candidate = f"{base[:USERNAME_MAX - len(tail)]}{tail}"
    return candidate
