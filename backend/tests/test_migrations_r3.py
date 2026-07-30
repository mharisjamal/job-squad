"""Phase R3 schema: the two new tables are created by create_all, and re-running
init_db is idempotent and never loses existing data (the live-DB safety gate)."""

from sqlalchemy import inspect, select

from app.db import init_db
from app.models import Resume, ResumeShare, User, UserAISettings


async def _table_names(engine) -> set[str]:
    async with engine.connect() as conn:
        return set(await conn.run_sync(lambda c: inspect(c).get_table_names()))


async def test_new_tables_are_created(asgi_app):
    names = await _table_names(asgi_app.state.engine)
    assert "user_ai_settings" in names
    assert "resume_shares" in names


async def test_init_db_is_idempotent_and_preserves_data(asgi_app):
    engine = asgi_app.state.engine
    sessionmaker = asgi_app.state.sessionmaker

    async with sessionmaker() as session:
        user = User(username="haris", display_name="Haris", email="haris@example.com")
        session.add(user)
        await session.flush()
        session.add(
            UserAISettings(
                user_id=user.id, provider="groq",
                base_url="https://api.groq.com/openai/v1",
                model="llama-3.3-70b-versatile", key_encrypted="ciphertext",
            )
        )
        resume = Resume(
            user_id=user.id, label="CV", filename="cv.pdf", kind="pdf",
            content_type="application/pdf", size_bytes=4, data=b"%PDF",
        )
        session.add(resume)
        await session.flush()
        session.add(ResumeShare(resume_id=resume.id, token="a" * 32))
        await session.commit()
        user_id, resume_id = user.id, resume.id

    # Re-running init_db (as every boot does) must not drop or wipe anything.
    await init_db(engine)

    async with sessionmaker() as session:
        settings = await session.get(UserAISettings, user_id)
        assert settings is not None
        assert settings.key_encrypted == "ciphertext"
        share = await session.scalar(
            select(ResumeShare).where(ResumeShare.resume_id == resume_id)
        )
        assert share is not None
        assert share.token == "a" * 32
