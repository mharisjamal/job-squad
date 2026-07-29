"""Email-OTP signup: off by default, active when SMTP is configured.

The mailer is monkeypatched so tests capture the code instead of sending mail;
no test ever opens an SMTP connection.
"""

from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.models import PendingRegistration, User, utcnow

SIGNUP = {
    "display_name": "Haris",
    "email": "haris@example.com",
    "password": "password123",
}


@pytest.fixture
async def otp_app(tmp_path, monkeypatch):
    """An app with SMTP configured, so otp_required is True."""
    monkeypatch.setenv("JOBSQUAD_DB_PATH", str(tmp_path / "otp.db"))
    monkeypatch.setenv("JOBSQUAD_SECRET", "test-secret-not-for-production")
    monkeypatch.setenv("JOBSQUAD_TOKEN_TTL_HOURS", "1")
    monkeypatch.setenv("JOBSQUAD_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("JOBSQUAD_SMTP_USER", "bot@example.com")
    monkeypatch.setenv("JOBSQUAD_SMTP_PASSWORD", "smtp-secret")
    from app.main import create_app

    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
def sent_codes(monkeypatch):
    """Capture verification codes instead of sending email."""
    captured: list[dict] = []

    def _fake_send(settings, to_email, code, display_name):
        captured.append(
            {"to": to_email, "code": code, "display_name": display_name}
        )

    monkeypatch.setattr("app.routers.auth.send_otp_email", _fake_send)
    return captured


@pytest.fixture
async def otp_client(otp_app, sent_codes):
    transport = ASGITransport(app=otp_app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.fixture(autouse=True)
def reset_start_throttle():
    from app.routers.auth import _OTP_STARTS

    _OTP_STARTS.clear()
    yield
    _OTP_STARTS.clear()


async def _start(otp_client, **overrides) -> dict:
    payload = {**SIGNUP, **overrides}
    return await otp_client.post("/api/auth/register/start", json=payload)


# ---------------------------------------------------------------------------
# SMTP unset: OTP is off and nothing about the old flow changes
# ---------------------------------------------------------------------------


async def test_config_reports_otp_off_without_smtp(client):
    resp = await client.get("/api/auth/config")
    assert resp.status_code == 200
    assert resp.json() == {"otp_required": False, "providers": []}


async def test_open_register_still_works_without_smtp(client, register):
    account = await register(username="haris")
    resp = await client.get("/api/auth/me", headers=account["headers"])
    assert resp.status_code == 200


async def test_start_and_verify_are_404_without_smtp(client):
    resp = await client.post("/api/auth/register/start", json=SIGNUP)
    assert resp.status_code == 404
    resp = await client.post(
        "/api/auth/register/verify",
        json={"email": SIGNUP["email"], "code": "123456"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# SMTP configured: OTP is required
# ---------------------------------------------------------------------------


async def test_config_reports_otp_on_and_needs_no_token(otp_client):
    resp = await otp_client.get("/api/auth/config")
    assert resp.status_code == 200
    assert resp.json() == {"otp_required": True, "providers": []}


async def test_resend_key_alone_turns_otp_on(tmp_path, monkeypatch):
    """A Resend key is a mail transport too: no SMTP host needed."""
    monkeypatch.setenv("JOBSQUAD_DB_PATH", str(tmp_path / "resend.db"))
    monkeypatch.setenv("JOBSQUAD_SECRET", "test-secret-not-for-production")
    monkeypatch.setenv("JOBSQUAD_RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("JOBSQUAD_MAIL_FROM", "JobSquad <noreply@example.com>")
    monkeypatch.delenv("JOBSQUAD_SMTP_HOST", raising=False)
    from app.main import create_app

    application = create_app()
    assert application.state.settings.otp_required is True

    captured: list[dict] = []
    monkeypatch.setattr(
        "app.routers.auth.send_otp_email",
        lambda settings, to_email, code, display_name: captured.append(
            {"to": to_email, "code": code}
        ),
    )
    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            resp = await http.get("/api/auth/config")
            assert resp.json()["otp_required"] is True
            resp = await http.post("/api/auth/register/start", json=SIGNUP)
            assert resp.status_code == 200, resp.text
            assert len(captured) == 1


async def test_open_register_forbidden_when_otp_required(otp_client):
    resp = await otp_client.post("/api/auth/register", json=SIGNUP)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Email verification is required on this server."


async def test_happy_path_start_verify_login(otp_client, sent_codes, otp_app):
    resp = await _start(otp_client)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "resend_after_seconds": 60}
    assert len(sent_codes) == 1
    assert sent_codes[0]["to"] == SIGNUP["email"]
    code = sent_codes[0]["code"]
    assert len(code) == 6 and code.isdigit()

    # No user exists until the code is verified.
    async with otp_app.state.sessionmaker() as session:
        assert await session.scalar(select(User)) is None

    resp = await otp_client.post(
        "/api/auth/register/verify", json={"email": SIGNUP["email"], "code": code}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # The handle is derived from the email local part, never chosen.
    assert body["user"]["username"] == "haris"
    assert body["user"]["email"] == SIGNUP["email"]

    # The token works.
    headers = {"Authorization": f"Bearer {body['token']}"}
    resp = await otp_client.get("/api/auth/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["username"] == "haris"

    # Exactly one user, and the pending row is gone.
    async with otp_app.state.sessionmaker() as session:
        users = (await session.scalars(select(User))).all()
        assert len(users) == 1
        assert users[0].email == SIGNUP["email"]
        assert (await session.scalars(select(PendingRegistration))).all() == []

    # The password from the signup works for a normal login by email.
    resp = await otp_client.post(
        "/api/auth/login",
        json={"identifier": SIGNUP["email"], "password": SIGNUP["password"]},
    )
    assert resp.status_code == 200


async def test_code_is_never_stored_in_plaintext(otp_client, sent_codes, otp_app):
    await _start(otp_client)
    code = sent_codes[0]["code"]
    async with otp_app.state.sessionmaker() as session:
        pending = await session.scalar(select(PendingRegistration))
        assert pending.otp_hash != code
        assert code not in pending.otp_hash
        assert len(pending.otp_hash) == 64  # HMAC-SHA256 hex
        # The plaintext code appears nowhere in the row.
        row_text = " ".join(
            str(getattr(pending, column))
            for column in ("email", "display_name", "password_hash", "otp_hash")
        )
        assert code not in row_text


async def test_wrong_code_401_and_increments_attempts(otp_client, sent_codes, otp_app):
    await _start(otp_client)
    resp = await otp_client.post(
        "/api/auth/register/verify",
        json={"email": SIGNUP["email"], "code": "000000"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "That code is not right."
    async with otp_app.state.sessionmaker() as session:
        pending = await session.scalar(select(PendingRegistration))
        assert pending.attempts == 1

    # The real code still works afterwards.
    resp = await otp_client.post(
        "/api/auth/register/verify",
        json={"email": SIGNUP["email"], "code": sent_codes[0]["code"]},
    )
    assert resp.status_code == 200


async def test_five_wrong_codes_burns_the_pending_row(otp_client, sent_codes, otp_app):
    await _start(otp_client)
    for _ in range(4):
        resp = await otp_client.post(
            "/api/auth/register/verify",
            json={"email": SIGNUP["email"], "code": "000000"},
        )
        assert resp.status_code == 401
    resp = await otp_client.post(
        "/api/auth/register/verify",
        json={"email": SIGNUP["email"], "code": "000000"},
    )
    assert resp.status_code == 429
    assert resp.json()["detail"] == "Too many wrong codes. Start the signup again."

    async with otp_app.state.sessionmaker() as session:
        assert (await session.scalars(select(PendingRegistration))).all() == []

    # Even the correct code is useless now.
    resp = await otp_client.post(
        "/api/auth/register/verify",
        json={"email": SIGNUP["email"], "code": sent_codes[0]["code"]},
    )
    assert resp.status_code == 404


async def test_expired_code_410(otp_client, sent_codes, otp_app):
    await _start(otp_client)
    async with otp_app.state.sessionmaker() as session:
        pending = await session.scalar(select(PendingRegistration))
        pending.expires_at = utcnow() - timedelta(minutes=1)
        await session.commit()

    resp = await otp_client.post(
        "/api/auth/register/verify",
        json={"email": SIGNUP["email"], "code": sent_codes[0]["code"]},
    )
    assert resp.status_code == 410
    assert resp.json()["detail"] == "That code expired. Request a new one."


async def test_resend_within_cooldown_429(otp_client, sent_codes):
    assert (await _start(otp_client)).status_code == 200
    resp = await _start(otp_client)
    assert resp.status_code == 429
    assert resp.json()["detail"] == "Wait a minute before requesting another code."
    assert len(sent_codes) == 1  # no second mail


async def test_resend_after_cooldown_issues_a_new_code(otp_client, sent_codes, otp_app):
    await _start(otp_client)
    first_code = sent_codes[0]["code"]
    async with otp_app.state.sessionmaker() as session:
        pending = await session.scalar(select(PendingRegistration))
        pending.last_sent_at = utcnow() - timedelta(seconds=120)
        await session.commit()

    resp = await _start(otp_client, display_name="Haris J")
    assert resp.status_code == 200
    assert len(sent_codes) == 2

    # The newest code verifies; the superseded one does not.
    resp = await otp_client.post(
        "/api/auth/register/verify",
        json={"email": SIGNUP["email"], "code": first_code},
    )
    assert resp.status_code == 401
    resp = await otp_client.post(
        "/api/auth/register/verify",
        json={"email": SIGNUP["email"], "code": sent_codes[1]["code"]},
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["display_name"] == "Haris J"


async def test_colliding_handle_gets_a_suffix_not_a_409(otp_client, sent_codes):
    """A second haris@... signs up fine; only the derived handle differs."""
    await _start(otp_client)
    await otp_client.post(
        "/api/auth/register/verify",
        json={"email": SIGNUP["email"], "code": sent_codes[0]["code"]},
    )
    resp = await _start(otp_client, email="haris@other.example")
    assert resp.status_code == 200
    resp = await otp_client.post(
        "/api/auth/register/verify",
        json={"email": "haris@other.example", "code": sent_codes[1]["code"]},
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["username"] == "haris2"


async def test_duplicate_email_at_start_409(otp_client, sent_codes):
    await _start(otp_client)
    await otp_client.post(
        "/api/auth/register/verify",
        json={"email": SIGNUP["email"], "code": sent_codes[0]["code"]},
    )
    resp = await _start(otp_client)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "An account already exists for that email."


async def test_invalid_email_422(otp_client):
    resp = await _start(otp_client, email="not-an-email")
    assert resp.status_code == 422


async def test_short_password_422(otp_client):
    resp = await _start(otp_client, password="short")
    assert resp.status_code == 422


async def test_verify_unknown_email_404(otp_client):
    resp = await otp_client.post(
        "/api/auth/register/verify",
        json={"email": "nobody@example.com", "code": "123456"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "No pending signup for that email. Start again."


async def test_ip_start_throttle_429(otp_client, sent_codes, otp_app):
    # Ten distinct emails from the same client IP are allowed, the 11th is not.
    for index in range(10):
        resp = await _start(otp_client, email=f"user{index}@example.com")
        assert resp.status_code == 200, resp.text
    resp = await _start(otp_client, email="user99@example.com")
    assert resp.status_code == 429
    assert len(sent_codes) == 10


async def test_smtp_failure_502(otp_client, monkeypatch):
    from app.mailer import MailError

    def _boom(settings, to_email, code, display_name):
        raise MailError("connection refused")

    monkeypatch.setattr("app.routers.auth.send_otp_email", _boom)
    resp = await _start(otp_client)
    assert resp.status_code == 502
    assert resp.json()["detail"] == (
        "Could not send the verification email. Check the server mail settings."
    )


# ---------------------------------------------------------------------------
# Lightweight migration for pre-existing databases
# ---------------------------------------------------------------------------


async def test_init_db_adds_email_column_to_legacy_users_table(tmp_path):
    """An old DB whose users table predates the email column must survive."""
    from app.db import init_db, make_engine

    db_path = tmp_path / "legacy.db"
    engine = make_engine(db_path)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE users ("
                " id INTEGER NOT NULL PRIMARY KEY,"
                " username VARCHAR(30) NOT NULL UNIQUE,"
                " display_name TEXT NOT NULL,"
                " password_hash TEXT NOT NULL,"
                " created_at DATETIME)"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO users (username, display_name, password_hash, created_at)"
                " VALUES ('legacy', 'Legacy User', 'pbkdf2_sha256$1$aa$bb', '2026-01-01')"
            )
        )

    await init_db(engine)

    async with engine.begin() as conn:
        columns = {row[1] for row in (await conn.execute(text("PRAGMA table_info(users)"))).all()}
        assert "email" in columns
        rows = (await conn.execute(text("SELECT username, email FROM users"))).all()
        assert rows == [("legacy", None)]
        # The new table was created alongside.
        tables = {
            row[0]
            for row in (
                await conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )
            ).all()
        }
        assert "pending_registrations" in tables

    # Running it again is a no-op (idempotent).
    await init_db(engine)
    async with engine.begin() as conn:
        rows = (await conn.execute(text("SELECT username, email FROM users"))).all()
        assert rows == [("legacy", None)]
    await engine.dispose()


async def test_init_db_makes_password_hash_nullable_and_keeps_rows(tmp_path):
    """The 12-step rebuild: old NOT NULL password_hash, rows and ids survive."""
    from app.db import init_db, make_engine

    engine = make_engine(tmp_path / "legacy_notnull.db")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE users ("
                " id INTEGER NOT NULL PRIMARY KEY,"
                " username VARCHAR(30) NOT NULL UNIQUE,"
                " display_name TEXT NOT NULL,"
                " password_hash TEXT NOT NULL,"
                " created_at DATETIME)"
            )
        )
        # A child table with a foreign key onto users must survive the rebuild.
        await conn.execute(
            text(
                "CREATE TABLE groups ("
                " id INTEGER NOT NULL PRIMARY KEY,"
                " name TEXT NOT NULL,"
                " invite_code VARCHAR(8) NOT NULL UNIQUE,"
                " owner_id INTEGER NOT NULL REFERENCES users(id),"
                " created_at DATETIME)"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO users (id, username, display_name, password_hash, created_at)"
                " VALUES (7, 'tester', 'Tester', 'pbkdf2_sha256$1$aa$bb', '2026-01-01'),"
                " (8, 'tester2', 'Tester Two', 'pbkdf2_sha256$1$cc$dd', '2026-01-02')"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO groups (id, name, invite_code, owner_id, created_at)"
                " VALUES (1, 'Job Hunt', 'ABCD2345', 7, '2026-01-01')"
            )
        )

    await init_db(engine)

    async with engine.begin() as conn:
        info = (await conn.execute(text("PRAGMA table_info(users)"))).all()
        by_name = {row[1]: row for row in info}
        assert by_name["password_hash"][3] == 0  # notnull cleared
        assert "email" in by_name and "avatar_url" in by_name
        rows = (
            await conn.execute(text("SELECT id, username, password_hash FROM users ORDER BY id"))
        ).all()
        assert [(r[0], r[1]) for r in rows] == [(7, "tester"), (8, "tester2")]
        assert all(r[2] for r in rows)  # password hashes intact
        # The child row still points at the same owner id.
        group_rows = (await conn.execute(text("SELECT owner_id FROM groups"))).all()
        assert group_rows == [(7,)]
        # A social account (no password) is now insertable.
        await conn.execute(
            text(
                "INSERT INTO users (username, display_name, password_hash, email)"
                " VALUES ('social', 'Social', NULL, 'social@example.com')"
            )
        )

    # Idempotent: a second run does not rebuild again or lose anything.
    await init_db(engine)
    async with engine.begin() as conn:
        rows = (await conn.execute(text("SELECT id FROM users ORDER BY id"))).all()
        assert [r[0] for r in rows][:2] == [7, 8]
    await engine.dispose()


async def test_init_db_is_idempotent_on_fresh_db(tmp_path):
    from app.db import init_db, make_engine

    engine = make_engine(tmp_path / "fresh.db")
    await init_db(engine)
    await init_db(engine)
    async with engine.begin() as conn:
        columns = {row[1] for row in (await conn.execute(text("PRAGMA table_info(users)"))).all()}
        assert "email" in columns
    await engine.dispose()
