"""JD-to-resume match report: coverage math, present/missing, the 409 cases,
cross-group and not-mine 404s, jd_text merge-upsert + 50k cap, lazy backfill."""

import pytest
from sqlalchemy import select

from app.models import Resume


@pytest.fixture
def upload_tex(client):
    """Upload a .tex resume whose plain text is exactly `body` (no LaTeX
    markup needed: the stripper leaves plain text untouched)."""

    async def _upload(headers, body, label="CV"):
        resp = await client.post(
            "/api/resumes",
            data={"label": label},
            files={"file": ("cv.tex", body.encode("utf-8"), "application/octet-stream")},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    return _upload


@pytest.fixture
def set_application(client):
    async def _set(headers, company_id, **fields):
        resp = await client.put(
            f"/api/companies/{company_id}/application", json=fields, headers=headers
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    return _set


async def _app_id(client, headers, gid):
    resp = await client.get(
        f"/api/groups/{gid}/applications", params={"user_id": "me"}, headers=headers
    )
    return resp.json()[0]["id"]


# ---------------------------------------------------------------------------
# Coverage math + present/missing
# ---------------------------------------------------------------------------


async def test_match_report_shape_and_coverage(
    client, register, make_group, make_company, upload_tex, set_application
):
    haris = await register(username="haris")
    group = await make_group(haris["headers"])
    company = await make_company(haris["headers"], group["id"], name="TechCorp")
    resume = await upload_tex(haris["headers"], "Python Django Docker web developer")
    await set_application(
        haris["headers"],
        company["id"],
        status="applied",
        resume_id=resume["id"],
        jd_text="We need Python, Django, Docker, AWS, and Kubernetes experience.",
    )
    app_id = await _app_id(client, haris["headers"], group["id"])

    resp = await client.get(f"/api/applications/{app_id}/match", headers=haris["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {
        "jd_skills", "coverage", "missing", "resume_id", "resume_label",
        "resume_text_available",
    }
    assert body["resume_id"] == resume["id"]
    assert body["resume_label"] == "CV"
    assert body["resume_text_available"] is True

    present = {e["skill"] for e in body["jd_skills"] if e["present"]}
    absent = {e["skill"] for e in body["jd_skills"] if not e["present"]}
    assert present == {"Python", "Django", "Docker"}
    assert absent == {"AWS", "Kubernetes"}
    assert set(body["missing"]) == {"AWS", "Kubernetes"}
    # 3 of 5 JD skills present.
    assert body["coverage"] == 60
    # jd_skills is ordered by first appearance in the JD.
    assert [e["skill"] for e in body["jd_skills"]] == [
        "Python", "Django", "Docker", "AWS", "Kubernetes",
    ]


async def test_coverage_rounds_to_nearest_int(
    client, register, make_group, make_company, upload_tex, set_application
):
    haris = await register(username="haris")
    group = await make_group(haris["headers"])
    company = await make_company(haris["headers"], group["id"], name="TechCorp")
    resume = await upload_tex(haris["headers"], "Python and Go")
    await set_application(
        haris["headers"],
        company["id"],
        status="applied",
        resume_id=resume["id"],
        jd_text="Python, Go, and Rust wanted.",
    )
    app_id = await _app_id(client, haris["headers"], group["id"])
    resp = await client.get(f"/api/applications/{app_id}/match", headers=haris["headers"])
    # 2 of 3 -> 66.67 -> 67.
    assert resp.json()["coverage"] == 67


async def test_coverage_zero_when_jd_has_no_detected_skills(
    client, register, make_group, make_company, upload_tex, set_application
):
    haris = await register(username="haris")
    group = await make_group(haris["headers"])
    company = await make_company(haris["headers"], group["id"], name="TechCorp")
    resume = await upload_tex(haris["headers"], "Python Django")
    await set_application(
        haris["headers"],
        company["id"],
        status="applied",
        resume_id=resume["id"],
        jd_text="We want a friendly, motivated teammate who loves shipping.",
    )
    app_id = await _app_id(client, haris["headers"], group["id"])
    resp = await client.get(f"/api/applications/{app_id}/match", headers=haris["headers"])
    body = resp.json()
    assert body["jd_skills"] == []
    assert body["missing"] == []
    assert body["coverage"] == 0


# ---------------------------------------------------------------------------
# 409 cases (each names what is missing)
# ---------------------------------------------------------------------------


async def test_409_when_both_jd_and_resume_missing(
    client, register, make_group, make_company, set_application
):
    haris = await register(username="haris")
    group = await make_group(haris["headers"])
    company = await make_company(haris["headers"], group["id"], name="TechCorp")
    await set_application(haris["headers"], company["id"], status="saved")
    app_id = await _app_id(client, haris["headers"], group["id"])

    resp = await client.get(f"/api/applications/{app_id}/match", headers=haris["headers"])
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Add a job description and attach a resume to see the match."


async def test_409_when_only_resume_missing(
    client, register, make_group, make_company, set_application
):
    haris = await register(username="haris")
    group = await make_group(haris["headers"])
    company = await make_company(haris["headers"], group["id"], name="TechCorp")
    await set_application(
        haris["headers"], company["id"], status="applied", jd_text="Python and Docker"
    )
    app_id = await _app_id(client, haris["headers"], group["id"])

    resp = await client.get(f"/api/applications/{app_id}/match", headers=haris["headers"])
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Attach a resume to see the match."


async def test_409_when_only_jd_missing(
    client, register, make_group, make_company, upload_tex, set_application
):
    haris = await register(username="haris")
    group = await make_group(haris["headers"])
    company = await make_company(haris["headers"], group["id"], name="TechCorp")
    resume = await upload_tex(haris["headers"], "Python Docker")
    await set_application(
        haris["headers"], company["id"], status="applied", resume_id=resume["id"]
    )
    app_id = await _app_id(client, haris["headers"], group["id"])

    resp = await client.get(f"/api/applications/{app_id}/match", headers=haris["headers"])
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Add a job description to see the match."


async def test_blank_jd_text_counts_as_missing(
    client, register, make_group, make_company, upload_tex, set_application
):
    """Whitespace-only jd_text is treated as no JD (409, not an empty report)."""
    haris = await register(username="haris")
    group = await make_group(haris["headers"])
    company = await make_company(haris["headers"], group["id"], name="TechCorp")
    resume = await upload_tex(haris["headers"], "Python")
    await set_application(
        haris["headers"],
        company["id"],
        status="applied",
        resume_id=resume["id"],
        jd_text="   \n  ",
    )
    app_id = await _app_id(client, haris["headers"], group["id"])
    resp = await client.get(f"/api/applications/{app_id}/match", headers=haris["headers"])
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Add a job description to see the match."


# ---------------------------------------------------------------------------
# Scoping: not mine / unknown / cross-group -> 404
# ---------------------------------------------------------------------------


async def test_someone_elses_application_is_404(
    client, register, make_group, make_company, upload_tex, set_application
):
    haris = await register(username="haris")
    ali = await register(username="ali")
    group = await make_group(haris["headers"])
    await client.post(
        "/api/groups/join",
        json={"invite_code": group["invite_code"]},
        headers=ali["headers"],
    )
    company = await make_company(haris["headers"], group["id"], name="TechCorp")
    resume = await upload_tex(ali["headers"], "Python")
    await set_application(
        ali["headers"], company["id"], status="applied", resume_id=resume["id"],
        jd_text="Python",
    )
    ali_app_id = await _app_id(client, ali["headers"], group["id"])

    # Haris shares the group but the row is Ali's: 404, no existence leak.
    resp = await client.get(
        f"/api/applications/{ali_app_id}/match", headers=haris["headers"]
    )
    assert resp.status_code == 404

    # A stranger outside the group also gets 404.
    mallory = await register(username="mallory")
    resp = await client.get(
        f"/api/applications/{ali_app_id}/match", headers=mallory["headers"]
    )
    assert resp.status_code == 404


async def test_unknown_application_is_404(client, register):
    haris = await register(username="haris")
    resp = await client.get("/api/applications/999999/match", headers=haris["headers"])
    assert resp.status_code == 404


async def test_match_requires_auth(client, register, make_group, make_company):
    haris = await register(username="haris")
    group = await make_group(haris["headers"])
    company = await make_company(haris["headers"], group["id"], name="TechCorp")
    await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "saved"},
        headers=haris["headers"],
    )
    app_id = await _app_id(client, haris["headers"], group["id"])
    resp = await client.get(f"/api/applications/{app_id}/match")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# jd_text merge semantics + 50k cap
# ---------------------------------------------------------------------------


async def test_jd_text_merge_upsert(
    client, register, make_group, make_company, set_application
):
    haris = await register(username="haris")
    group = await make_group(haris["headers"])
    company = await make_company(haris["headers"], group["id"], name="TechCorp")

    first = await set_application(
        haris["headers"], company["id"], status="applied", jd_text="Python role", notes="hi"
    )
    assert first["jd_text"] == "Python role"

    # A status-only PUT preserves the JD (kanban drag / inline select).
    second = await set_application(haris["headers"], company["id"], status="interview")
    assert second["jd_text"] == "Python role"
    assert second["notes"] == "hi"

    # An explicit null clears just the JD.
    third = await set_application(
        haris["headers"], company["id"], status="interview", jd_text=None
    )
    assert third["jd_text"] is None
    assert third["notes"] == "hi"


async def test_jd_text_50k_cap(client, register, make_group, make_company):
    haris = await register(username="haris")
    group = await make_group(haris["headers"])
    company = await make_company(haris["headers"], group["id"], name="TechCorp")

    at_cap = await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "applied", "jd_text": "x" * 50000},
        headers=haris["headers"],
    )
    assert at_cap.status_code == 200

    over_cap = await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "applied", "jd_text": "x" * 50001},
        headers=haris["headers"],
    )
    assert over_cap.status_code == 422


# ---------------------------------------------------------------------------
# Lazy backfill of extracted_text for pre-extraction resume rows
# ---------------------------------------------------------------------------


async def test_lazy_backfill_extracts_when_text_is_null(
    client, asgi_app, register, make_group, make_company, upload_tex, set_application
):
    haris = await register(username="haris")
    group = await make_group(haris["headers"])
    company = await make_company(haris["headers"], group["id"], name="TechCorp")
    resume = await upload_tex(haris["headers"], "Python Kubernetes")
    await set_application(
        haris["headers"], company["id"], status="applied", resume_id=resume["id"],
        jd_text="Python and Kubernetes",
    )

    # Simulate a row created before extraction existed: extracted_text = NULL.
    sessionmaker = asgi_app.state.sessionmaker
    async with sessionmaker() as session:
        row = await session.get(Resume, resume["id"])
        row.extracted_text = None
        await session.commit()

    app_id = await _app_id(client, haris["headers"], group["id"])
    resp = await client.get(f"/api/applications/{app_id}/match", headers=haris["headers"])
    assert resp.status_code == 200
    # The backfill made the match work.
    assert {e["skill"] for e in resp.json()["jd_skills"] if e["present"]} == {
        "Python", "Kubernetes",
    }

    # And it was persisted, so a second request needs no re-extraction.
    async with sessionmaker() as session:
        stored = await session.scalar(
            select(Resume.extracted_text).where(Resume.id == resume["id"])
        )
        assert stored and "Python" in stored


async def test_upload_populates_extracted_text(client, asgi_app, register, upload_tex):
    haris = await register(username="haris")
    resume = await upload_tex(haris["headers"], "Go Rust systems programming")
    async with asgi_app.state.sessionmaker() as session:
        stored = await session.scalar(
            select(Resume.extracted_text).where(Resume.id == resume["id"])
        )
    assert stored == "Go Rust systems programming"


# ---------------------------------------------------------------------------
# Unreadable resume (image-only/scanned PDF) -> not a fake 0% all-gaps report
# ---------------------------------------------------------------------------


async def test_unreadable_resume_flags_text_unavailable(
    client, asgi_app, register, make_group, make_company, upload_tex, set_application
):
    haris = await register(username="haris")
    group = await make_group(haris["headers"])
    company = await make_company(haris["headers"], group["id"], name="TechCorp")
    resume = await upload_tex(haris["headers"], "Python Docker")
    await set_application(
        haris["headers"], company["id"], status="applied", resume_id=resume["id"],
        jd_text="We need Python and Docker.",
    )

    # Simulate an image-only PDF: extraction already ran and found nothing ("").
    # (Empty string, not NULL, so the lazy backfill does not re-extract.)
    async with asgi_app.state.sessionmaker() as session:
        row = await session.get(Resume, resume["id"])
        row.extracted_text = ""
        await session.commit()

    app_id = await _app_id(client, haris["headers"], group["id"])
    resp = await client.get(f"/api/applications/{app_id}/match", headers=haris["headers"])
    assert resp.status_code == 200
    body = resp.json()
    # The JD skills are still reported so the frontend can render them...
    assert [e["skill"] for e in body["jd_skills"]] == ["Python", "Docker"]
    # ...but the honest signal says the resume text could not be read, so the UI
    # shows a notice instead of presenting the (misleading) 0% as a real result.
    assert body["resume_text_available"] is False
    assert body["coverage"] == 0
    assert set(body["missing"]) == {"Python", "Docker"}
