"""Resume vault: upload validation, caps, list/rename/delete, file authz
matrix, application attachment (merge semantics), and outcome stats."""

import pytest

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
DOCX_BYTES = b"PK\x03\x04" + b"\x00" * 64
TEX_BYTES = b"\\documentclass{article}\\begin{document}Hi\\end{document}"


@pytest.fixture
def upload(client):
    async def _upload(
        headers,
        label="CV v1",
        filename="cv.pdf",
        content=PDF_BYTES,
        content_type="application/octet-stream",
    ):
        return await client.post(
            "/api/resumes",
            data={"label": label},
            files={"file": (filename, content, content_type)},
            headers=headers,
        )

    return _upload


@pytest.fixture
def attach(client):
    """PUT my application on a company with a resume attached."""

    async def _attach(headers, company_id, resume_id, status="applied"):
        resp = await client.put(
            f"/api/companies/{company_id}/application",
            json={"status": status, "resume_id": resume_id},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    return _attach


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


async def test_upload_pdf_returns_exact_wire_shape(register, upload):
    account = await register(username="haris")
    resp = await upload(account["headers"], label="Backend CV", filename="cv.pdf")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {
        "id", "label", "filename", "kind", "size_bytes", "created_at", "attached_count",
    }
    assert body["label"] == "Backend CV"
    assert body["filename"] == "cv.pdf"
    assert body["kind"] == "pdf"
    assert body["size_bytes"] == len(PDF_BYTES)
    assert body["attached_count"] == 0
    assert body["created_at"].endswith("Z")


async def test_kind_detection_magic_bytes_and_tex_extension(register, upload):
    account = await register(username="haris")

    # PK zip magic -> docx, whatever the filename says.
    resp = await upload(account["headers"], filename="cv.docx", content=DOCX_BYTES)
    assert resp.status_code == 200
    assert resp.json()["kind"] == "docx"

    # .tex is plain text: extension decides.
    resp = await upload(account["headers"], filename="cv.tex", content=TEX_BYTES)
    assert resp.status_code == 200
    assert resp.json()["kind"] == "tex"

    # Magic bytes beat the extension.
    resp = await upload(account["headers"], filename="sneaky.tex", content=PDF_BYTES)
    assert resp.status_code == 200
    assert resp.json()["kind"] == "pdf"


async def test_upload_rejects_unsupported_and_empty_files(register, upload):
    account = await register(username="haris")
    resp = await upload(account["headers"], filename="cv.txt", content=b"plain text")
    assert resp.status_code == 422
    resp = await upload(account["headers"], filename="cv.pdf", content=b"")
    assert resp.status_code == 422


async def test_upload_label_validation(register, upload):
    account = await register(username="haris")
    resp = await upload(account["headers"], label="   ")
    assert resp.status_code == 422
    resp = await upload(account["headers"], label="x" * 81)
    assert resp.status_code == 422
    resp = await upload(account["headers"], label="x" * 80)
    assert resp.status_code == 200


async def test_upload_size_cap_413(register, upload):
    account = await register(username="haris")
    over_cap = b"%PDF" + b"\x00" * (2 * 1024 * 1024 - 3)  # 2 MB + 1 byte
    resp = await upload(account["headers"], content=over_cap)
    assert resp.status_code == 413

    # Far over the cap the body-size middleware rejects it before parsing.
    huge = b"%PDF" + b"\x00" * (3 * 1024 * 1024)
    resp = await upload(account["headers"], content=huge)
    assert resp.status_code == 413


async def test_upload_ten_per_user_cap_409(register, upload):
    account = await register(username="haris")
    for n in range(10):
        resp = await upload(account["headers"], label=f"CV {n}")
        assert resp.status_code == 200, resp.text
    resp = await upload(account["headers"], label="one too many")
    assert resp.status_code == 409

    # The cap is per user, not global.
    other = await register(username="ali")
    resp = await upload(other["headers"], label="ali cv")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# List / rename / delete
# ---------------------------------------------------------------------------


async def test_list_is_mine_only_with_attached_count(
    client, register, make_group, make_company, upload, attach
):
    haris = await register(username="haris")
    ali = await register(username="ali")
    first = (await upload(haris["headers"], label="CV v1")).json()
    second = (await upload(haris["headers"], label="CV v2")).json()
    await upload(ali["headers"], label="ali cv")

    group = await make_group(haris["headers"])
    company_a = await make_company(haris["headers"], group["id"], name="TechCorp")
    company_b = await make_company(haris["headers"], group["id"], name="DataInc")
    await attach(haris["headers"], company_a["id"], second["id"])
    await attach(haris["headers"], company_b["id"], second["id"])

    resp = await client.get("/api/resumes", headers=haris["headers"])
    assert resp.status_code == 200
    rows = resp.json()
    assert [row["label"] for row in rows] == ["CV v2", "CV v1"]  # newest first
    by_id = {row["id"]: row for row in rows}
    assert by_id[second["id"]]["attached_count"] == 2
    assert by_id[first["id"]]["attached_count"] == 0

    resp = await client.get("/api/resumes", headers=ali["headers"])
    assert [row["label"] for row in resp.json()] == ["ali cv"]


async def test_rename_resume(client, register, upload):
    haris = await register(username="haris")
    ali = await register(username="ali")
    resume = (await upload(haris["headers"], label="old name")).json()

    resp = await client.patch(
        f"/api/resumes/{resume['id']}", json={"label": "new name"}, headers=haris["headers"]
    )
    assert resp.status_code == 200
    assert resp.json()["label"] == "new name"

    # Someone else's resume is a 404, not a 403 (no existence leak).
    resp = await client.patch(
        f"/api/resumes/{resume['id']}", json={"label": "mine now"}, headers=ali["headers"]
    )
    assert resp.status_code == 404

    resp = await client.patch(
        f"/api/resumes/{resume['id']}", json={"label": "  "}, headers=haris["headers"]
    )
    assert resp.status_code == 422
    resp = await client.patch(
        f"/api/resumes/{resume['id']}", json={"label": "x" * 81}, headers=haris["headers"]
    )
    assert resp.status_code == 422


async def test_delete_resume_detaches_applications(
    client, register, make_group, make_company, upload, attach
):
    haris = await register(username="haris")
    ali = await register(username="ali")
    resume = (await upload(haris["headers"], label="CV")).json()
    group = await make_group(haris["headers"])
    company = await make_company(haris["headers"], group["id"], name="TechCorp")
    row = await attach(haris["headers"], company["id"], resume["id"])
    assert row["resume_id"] == resume["id"]

    resp = await client.delete(f"/api/resumes/{resume['id']}", headers=ali["headers"])
    assert resp.status_code == 404  # not the owner

    resp = await client.delete(f"/api/resumes/{resume['id']}", headers=haris["headers"])
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    resp = await client.delete(f"/api/resumes/{resume['id']}", headers=haris["headers"])
    assert resp.status_code == 404  # already gone

    # The application survives with resume_id cleared by the FK.
    resp = await client.get(
        f"/api/groups/{group['id']}/applications", headers=haris["headers"]
    )
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["resume_id"] is None
    assert rows[0]["resume_label"] is None
    assert rows[0]["status"] == "applied"


# ---------------------------------------------------------------------------
# File serving + authz matrix
# ---------------------------------------------------------------------------


async def test_file_owner_gets_bytes_and_hardening_headers(client, register, upload):
    haris = await register(username="haris")
    resume = (await upload(haris["headers"], label="CV", filename="cv.pdf")).json()

    resp = await client.get(f"/api/resumes/{resume['id']}/file", headers=haris["headers"])
    assert resp.status_code == 200
    assert resp.content == PDF_BYTES
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["content-disposition"] == 'inline; filename="cv.pdf"'
    assert resp.headers["x-content-type-options"] == "nosniff"


async def test_file_authz_matrix(
    client, register, make_group, make_company, upload, attach
):
    """Owner 200; squadmate-with-attachment 200; squadmate-without 404;
    stranger 404."""
    haris = await register(username="haris")
    ali = await register(username="ali")
    mallory = await register(username="mallory")
    group = await make_group(haris["headers"])
    await client.post(
        "/api/groups/join",
        json={"invite_code": group["invite_code"]},
        headers=ali["headers"],
    )
    company = await make_company(haris["headers"], group["id"], name="TechCorp")

    attached = (await upload(haris["headers"], label="attached")).json()
    private = (await upload(haris["headers"], label="private")).json()
    await attach(haris["headers"], company["id"], attached["id"])

    # Owner sees both.
    for rid in (attached["id"], private["id"]):
        resp = await client.get(f"/api/resumes/{rid}/file", headers=haris["headers"])
        assert resp.status_code == 200

    # Squadmate sees the attached one (it is on an application in their group)...
    resp = await client.get(f"/api/resumes/{attached['id']}/file", headers=ali["headers"])
    assert resp.status_code == 200
    assert resp.content == PDF_BYTES
    # ...but not the unattached one, even though they share a group.
    resp = await client.get(f"/api/resumes/{private['id']}/file", headers=ali["headers"])
    assert resp.status_code == 404

    # A stranger sees neither, attached or not.
    for rid in (attached["id"], private["id"]):
        resp = await client.get(f"/api/resumes/{rid}/file", headers=mallory["headers"])
        assert resp.status_code == 404


async def test_file_visibility_requires_the_shared_group(
    client, register, make_group, make_company, upload, attach
):
    """Attachment in group A grants nothing to a user who only shares group B."""
    haris = await register(username="haris")
    ali = await register(username="ali")
    group_a = await make_group(haris["headers"], name="Group A")
    group_b = await make_group(haris["headers"], name="Group B")
    await client.post(
        "/api/groups/join",
        json={"invite_code": group_b["invite_code"]},
        headers=ali["headers"],
    )
    company_a = await make_company(haris["headers"], group_a["id"], name="TechCorp")
    resume = (await upload(haris["headers"], label="CV")).json()
    await attach(haris["headers"], company_a["id"], resume["id"])

    resp = await client.get(f"/api/resumes/{resume['id']}/file", headers=ali["headers"])
    assert resp.status_code == 404


async def test_file_rejects_query_token(client, register, upload):
    """The ?access_token= allowlist (SSE + CSV exports) must not widen to
    resume files; the frontend fetches with the Bearer header into a blob."""
    haris = await register(username="haris")
    resume = (await upload(haris["headers"], label="CV")).json()

    resp = await client.get(
        f"/api/resumes/{resume['id']}/file", params={"access_token": haris["token"]}
    )
    assert resp.status_code == 401


async def test_deleted_and_unknown_resume_file_404(client, register, upload):
    haris = await register(username="haris")
    resp = await client.get("/api/resumes/99999/file", headers=haris["headers"])
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Application attachment (PUT merge semantics + serializers)
# ---------------------------------------------------------------------------


async def test_put_accepts_resume_id_with_merge_semantics(
    client, register, make_group, make_company, upload
):
    haris = await register(username="haris")
    group = await make_group(haris["headers"])
    company = await make_company(haris["headers"], group["id"], name="TechCorp")
    resume = (await upload(haris["headers"], label="Backend CV")).json()

    resp = await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "applied", "resume_id": resume["id"], "notes": "sent"},
        headers=haris["headers"],
    )
    assert resp.status_code == 200
    row = resp.json()
    assert row["resume_id"] == resume["id"]
    assert row["resume_label"] == "Backend CV"

    # A status-only PUT (kanban drag) preserves the attachment.
    resp = await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "interview"},
        headers=haris["headers"],
    )
    row = resp.json()
    assert row["status"] == "interview"
    assert row["resume_id"] == resume["id"]
    assert row["resume_label"] == "Backend CV"
    assert row["notes"] == "sent"

    # An explicit null clears it.
    resp = await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "interview", "resume_id": None},
        headers=haris["headers"],
    )
    row = resp.json()
    assert row["resume_id"] is None
    assert row["resume_label"] is None
    assert row["notes"] == "sent"


async def test_put_rejects_foreign_or_unknown_resume(
    client, register, make_group, make_company, upload
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
    ali_resume = (await upload(ali["headers"], label="ali cv")).json()

    # Someone else's resume: 422, and no row is created.
    resp = await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "applied", "resume_id": ali_resume["id"]},
        headers=haris["headers"],
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Unknown resume"

    resp = await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "applied", "resume_id": 99999},
        headers=haris["headers"],
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Unknown resume"

    resp = await client.get(
        f"/api/groups/{group['id']}/applications", headers=haris["headers"]
    )
    assert resp.json() == []


async def test_brief_detail_and_list_serializers_carry_resume(
    client, register, make_group, make_company, upload, attach
):
    haris = await register(username="haris")
    group = await make_group(haris["headers"])
    company = await make_company(haris["headers"], group["id"], name="TechCorp")
    resume = (await upload(haris["headers"], label="Backend CV")).json()
    await attach(haris["headers"], company["id"], resume["id"])

    # ApplicationBrief on the company list.
    resp = await client.get(
        f"/api/groups/{group['id']}/companies", headers=haris["headers"]
    )
    brief = resp.json()[0]["applications"][0]
    assert brief["resume_id"] == resume["id"]
    assert brief["resume_label"] == "Backend CV"

    # ApplicationFull on the company detail.
    resp = await client.get(f"/api/companies/{company['id']}", headers=haris["headers"])
    full = resp.json()["applications"][0]
    assert full["resume_id"] == resume["id"]
    assert full["resume_label"] == "Backend CV"

    # ApplicationFull on the group-wide list.
    resp = await client.get(
        f"/api/groups/{group['id']}/applications", headers=haris["headers"]
    )
    assert resp.json()[0]["resume_label"] == "Backend CV"


# ---------------------------------------------------------------------------
# Outcome stats
# ---------------------------------------------------------------------------


async def test_resume_stats_counts_outcomes(
    client, register, make_group, make_company, upload, attach
):
    haris = await register(username="haris")
    group = await make_group(haris["headers"])
    resume_a = (await upload(haris["headers"], label="CV A")).json()
    resume_b = (await upload(haris["headers"], label="CV B")).json()
    resume_c = (await upload(haris["headers"], label="CV C")).json()

    statuses_for_a = ("assessment", "interview", "offer", "applied")
    for n, status in enumerate(statuses_for_a):
        company = await make_company(haris["headers"], group["id"], name=f"A-{n}")
        await attach(haris["headers"], company["id"], resume_a["id"], status=status)
    company = await make_company(haris["headers"], group["id"], name="B-0")
    await attach(haris["headers"], company["id"], resume_b["id"], status="rejected")
    company = await make_company(haris["headers"], group["id"], name="B-1")
    await attach(haris["headers"], company["id"], resume_b["id"], status="ghosted")

    resp = await client.get("/api/resumes/stats", headers=haris["headers"])
    assert resp.status_code == 200
    stats = {entry["resume_id"]: entry for entry in resp.json()}
    assert set(stats[resume_a["id"]].keys()) == {
        "resume_id", "label", "applications", "interviews", "offers", "rejected", "ghosted",
    }

    a = stats[resume_a["id"]]
    assert a["label"] == "CV A"
    assert a["applications"] == 4
    assert a["interviews"] == 2  # assessment + interview
    assert a["offers"] == 1
    assert a["rejected"] == 0
    assert a["ghosted"] == 0

    b = stats[resume_b["id"]]
    assert b["applications"] == 2
    assert b["interviews"] == 0
    assert b["rejected"] == 1
    assert b["ghosted"] == 1

    c = stats[resume_c["id"]]
    assert c["applications"] == 0
    assert c["interviews"] == 0

    # Stats are mine only: another user sees an empty list.
    ali = await register(username="ali")
    resp = await client.get("/api/resumes/stats", headers=ali["headers"])
    assert resp.json() == []
