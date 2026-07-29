"""Stdlib-only auth primitives: PBKDF2 password hashing + hand-rolled HS256 JWT.

The JWT decoder never trusts the token's alg header: signatures are always
verified as HS256 with a constant-time compare.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time

PBKDF2_ITERATIONS = 250_000
_SCHEME = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"{_SCHEME}${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations_s, salt_hex, hash_hex = stored.split("$")
        if scheme != _SCHEME:
            return False
        iterations = int(iterations_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        # Inside the try: a malformed stored hash (e.g. negative iteration
        # count) must yield False, never an exception.
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(digest, expected)


_TO_STD_B64 = str.maketrans("-_", "+/")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(segment: str) -> bytes:
    """Strict base64url decode: exactly one textual form per byte string.

    Rejects padding characters, non-alphabet characters (validate=True) and
    non-canonical encodings (re-encode comparison), so signature segments
    like sig+"==" or sig+"!!" cannot alias a valid signature.
    """
    if len(segment) % 4 == 1:
        raise ValueError("invalid base64url length")
    padded = segment.translate(_TO_STD_B64) + "=" * (-len(segment) % 4)
    decoded = base64.b64decode(padded, validate=True)
    if _b64url_encode(decoded) != segment:
        raise ValueError("non-canonical base64url")
    return decoded


def jwt_encode(payload: dict, secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    head_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{head_b64}.{payload_b64}"
    signature = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256)
    return f"{signing_input}.{_b64url_encode(signature.digest())}"


def jwt_decode(token: str, secret: str) -> dict | None:
    """Return the payload if the token is valid and unexpired, else None."""
    try:
        head_b64, payload_b64, sig_b64 = token.split(".")
    except (ValueError, AttributeError):
        return None
    signing_input = f"{head_b64}.{payload_b64}".encode("ascii", errors="replace")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    try:
        actual = _b64url_decode(sig_b64)
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(expected, actual):
        return None
    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    exp = payload.get("exp")
    if not isinstance(exp, int | float) or time.time() > exp:
        return None
    return payload


def make_token(user_id: int, secret: str, ttl_hours: int) -> str:
    payload = {"sub": str(user_id), "exp": int(time.time()) + ttl_hours * 3600}
    return jwt_encode(payload, secret)
