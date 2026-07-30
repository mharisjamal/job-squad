"""Public resume share links: owner-only PDF sharing, token reuse, public serve,
revocation, and the 404/422 guards. The public GET /r/{token} carries no auth."""

import pytest

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
TEX_BYTES = b"\\documentclass{article}\\begin{document}Hi\\end{document}"


@pytest.fixture
def upload(client):
    async def _upload(headers, filename="cv.pdf", content=PDF_BYTES, label="CV"):
        resp = await client.post(
            "/api/resumes",
            data={"label": label},
            files={"file": (filename, content, "application/octet-stream")},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    return _upload


def _token_from_url(url: str) -> str:
    assert url.startswith("http://localhost:8100/r/"), url
    return url.rsplit("/", 1)[-1]


async def test_share_create_serve_and_revoke(client, register, upload):
    account = await register(username="haris")
    resume = await upload(account["headers"])

    resp = await client.post(
        f"/api/resumes/{resume['id']}/share", headers=account["headers"]
    )
    assert resp.status_code == 200, resp.text
    url = resp.json()["url"]
    token = _token_from_url(url)
    assert len(token) == 32  # 16 bytes -> 32 hex chars

    # Public serve: no auth header, returns the PDF bytes inline.
    served = await client.get(f"/r/{token}")
    assert served.status_code == 200, served.text
    assert served.content == PDF_BYTES
    assert served.headers["content-type"].startswith("application/pdf")
    assert served.headers["x-content-type-options"] == "nosniff"

    # Revoke, then the same token 404s.
    revoked = await client.delete(
        f"/api/resumes/{resume['id']}/share", headers=account["headers"]
    )
    assert revoked.status_code == 200
    gone = await client.get(f"/r/{token}")
    assert gone.status_code == 404


async def test_share_reuses_active_token(client, register, upload):
    account = await register(username="haris")
    resume = await upload(account["headers"])
    first = await client.post(
        f"/api/resumes/{resume['id']}/share", headers=account["headers"]
    )
    second = await client.post(
        f"/api/resumes/{resume['id']}/share", headers=account["headers"]
    )
    assert first.json()["url"] == second.json()["url"]


async def test_share_only_pdf_kind(client, register, upload):
    account = await register(username="haris")
    tex = await upload(account["headers"], filename="cv.tex", content=TEX_BYTES)
    resp = await client.post(
        f"/api/resumes/{tex['id']}/share", headers=account["headers"]
    )
    assert resp.status_code == 422
    assert "PDF" in resp.json()["detail"]


async def test_share_owner_only(client, register, upload):
    owner = await register(username="haris")
    resume = await upload(owner["headers"])
    stranger = await register(username="mallory")
    resp = await client.post(
        f"/api/resumes/{resume['id']}/share", headers=stranger["headers"]
    )
    # Someone else's resume 404s (no existence leak), never shares it.
    assert resp.status_code == 404


async def test_unknown_token_404(client):
    resp = await client.get("/r/deadbeefdeadbeefdeadbeefdeadbeef")
    assert resp.status_code == 404


async def test_share_requires_auth(client, register, upload):
    account = await register(username="haris")
    resume = await upload(account["headers"])
    # The create/revoke routes are authenticated; the public serve is not.
    assert (await client.post(f"/api/resumes/{resume['id']}/share")).status_code == 401
    assert (await client.delete(f"/api/resumes/{resume['id']}/share")).status_code == 401
