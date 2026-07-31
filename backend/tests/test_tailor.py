"""AI resume tailoring: tex vs advice response shapes, the 409 prerequisite
cases, malformed-JSON retry then 502, and the system-prompt constraint gate.
All AI calls are mocked - no real network, no real key."""

import io
import json

import pytest

import app.ai as ai_module

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def upload_tex(client):
    async def _upload(headers, body="Python Django Docker developer", label="CV"):
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
def upload_docx(client):
    """A real .docx whose extracted text is `body` (python-docx is a dep)."""

    async def _upload(headers, body="Python Django Docker developer", label="CV"):
        from docx import Document

        document = Document()
        document.add_paragraph(body)
        buffer = io.BytesIO()
        document.save(buffer)
        resp = await client.post(
            "/api/resumes",
            data={"label": label},
            files={
                "file": (
                    "cv.docx",
                    buffer.getvalue(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
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


@pytest.fixture
def configure_ai(client):
    async def _configure(headers, provider="groq", key="test-key"):
        resp = await client.put(
            "/api/settings/ai", json={"provider": provider, "key": key}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    return _configure


def _mock_reply(monkeypatch, *replies):
    """Make ai.chat_completion return each reply in turn; captures the messages."""
    calls = {"count": 0, "messages": []}
    sequence = list(replies)

    async def fake_chat_completion(**kwargs):
        calls["messages"].append(kwargs["messages"])
        idx = min(calls["count"], len(sequence) - 1)
        calls["count"] += 1
        return sequence[idx]

    monkeypatch.setattr(ai_module, "chat_completion", fake_chat_completion)
    return calls


def _tex_reply(tex: str, changes: list[str], end: bool = True) -> str:
    """Build a sentinel-delimited tex tailoring reply (the new tex contract)."""
    body = (
        "===CHANGES===\n"
        + "".join(f"- {c}\n" for c in changes)
        + "===TAILORED_TEX===\n"
        + tex
    )
    if end:
        body += "\n===END==="
    return body


# ---------------------------------------------------------------------------
# System-prompt constraint gate (unit; the R3 verifier requires these)
# ---------------------------------------------------------------------------


def test_system_prompt_encodes_the_researched_constraints():
    for kind in ("tex", "pdf"):
        prompt = ai_module.build_tailor_system_prompt(kind)
        # 1: never invent facts
        assert "NEVER invent" in prompt
        assert "already be present in the candidate's resume" in prompt
        # contact block frozen
        assert "contact block" in prompt and "FROZEN" in prompt
        # edits limited to rephrasing/reordering/emphasis
        assert "rephrasing, reordering, and re-emphasizing" in prompt
        # no keyword stuffing
        assert "keyword-stuff" in prompt
        # no hidden / invisible text
        assert "invisible text" in prompt
        assert "hidden" in prompt
        # mirror terminology only if genuinely held
        assert "Mirror the job description's exact terminology ONLY" in prompt
        # quantified STAR bullets, only real numbers
        assert "STAR-style bullets" in prompt
        assert "ONLY numbers already present" in prompt
        # gaps reported, not written in
        assert "GAP suggestion" in prompt


def test_tex_prompt_uses_sentinels_and_advice_prompt_uses_json():
    tex_prompt = ai_module.build_tailor_system_prompt("tex")
    # The tex path is sentinel-delimited plain text, NOT JSON (JSON-escaping
    # backslash-heavy LaTeX is what mid-tier models fail).
    assert "===TAILORED_TEX===" in tex_prompt
    assert "===CHANGES===" in tex_prompt
    assert "===END===" in tex_prompt
    assert "Do NOT return JSON" in tex_prompt
    # The advice path stays on JSON.
    assert "suggestions" in ai_module.build_tailor_system_prompt("pdf")
    assert "keywords_to_add" in ai_module.build_tailor_system_prompt("docx")


# ---------------------------------------------------------------------------
# Tex path
# ---------------------------------------------------------------------------


async def test_tailor_tex_returns_tailored_tex_and_changes(
    client, register, make_group, make_company, upload_tex, set_application,
    configure_ai, monkeypatch,
):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"])
    resume = await upload_tex(account["headers"])
    await set_application(
        account["headers"], company["id"],
        status="applied", resume_id=resume["id"],
        jd_text="We need Python, Django, and Kubernetes.",
    )
    await configure_ai(account["headers"])
    app_id = await _app_id(client, account["headers"], group["id"])

    reply = _tex_reply(
        "\\documentclass{article}\\begin{document}Hi\\end{document}",
        ["Reordered skills to lead with Python", "Sharpened the summary"],
    )
    calls = _mock_reply(monkeypatch, reply)

    resp = await client.post(
        f"/api/applications/{app_id}/tailor",
        json={"resume_id": resume["id"]},
        headers=account["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "tex"
    assert body["tailored_tex"].startswith("\\documentclass")
    assert body["changes"] == [
        "Reordered skills to lead with Python", "Sharpened the summary"
    ]
    # The system prompt (with constraints) actually reached the client.
    system_message = calls["messages"][0][0]
    assert system_message["role"] == "system"
    assert "NEVER invent" in system_message["content"]
    # The JD and resume source were in the user message.
    user_message = calls["messages"][0][1]["content"]
    assert "Kubernetes" in user_message
    assert "Python Django Docker developer" in user_message


# ---------------------------------------------------------------------------
# Tex sentinel parser (unit) - the fix for backslash-heavy JSON failures
# ---------------------------------------------------------------------------


def test_parse_tailored_tex_valid():
    reply = _tex_reply(
        "\\documentclass{article}\\begin{document}Hi\\end{document}",
        ["did a", "did b"],
    )
    parsed = ai_module.parse_tailored_tex(reply)
    assert parsed is not None
    assert parsed["tailored_tex"] == "\\documentclass{article}\\begin{document}Hi\\end{document}"
    assert parsed["changes"] == ["did a", "did b"]


def test_parse_tailored_tex_without_end_marker():
    # No ===END===: the tex block runs to the end of the message.
    reply = _tex_reply("\\documentclass{article}\nBody to the end", ["x"], end=False)
    parsed = ai_module.parse_tailored_tex(reply)
    assert parsed is not None
    assert parsed["tailored_tex"] == "\\documentclass{article}\nBody to the end"


def test_parse_tailored_tex_missing_source_marker_is_none():
    assert ai_module.parse_tailored_tex("just some prose, no markers") is None
    # A JSON reply (the old contract) no longer parses on the tex path.
    assert ai_module.parse_tailored_tex('{"tailored_tex": "x"}') is None


def test_parse_tailored_tex_requires_documentclass():
    # Marker present but the block is not a real LaTeX document -> parse failure.
    reply = "===TAILORED_TEX===\nnot really latex\n===END==="
    assert ai_module.parse_tailored_tex(reply) is None
    # Empty tex block -> parse failure.
    assert ai_module.parse_tailored_tex("===TAILORED_TEX===\n\n===END===") is None


def test_parse_tailored_tex_preserves_backslashes():
    # The whole point: raw LaTeX with many backslashes survives verbatim (no
    # JSON escaping, which mid-tier models get wrong most of the time).
    tex = (
        "\\documentclass{article}\n\\usepackage{geometry}\n"
        "\\begin{document}\n\\section{Experience}\n\\textbf{Engineer} at ACME\n"
        "\\end{document}"
    )
    parsed = ai_module.parse_tailored_tex(_tex_reply(tex, ["reworded a bullet"]))
    assert parsed is not None
    assert parsed["tailored_tex"] == tex
    assert parsed["tailored_tex"].count("\\") == tex.count("\\")


def test_parse_tailored_tex_strips_code_fence():
    reply = (
        "===TAILORED_TEX===\n```latex\n\\documentclass{article}\nHi\n```\n===END==="
    )
    parsed = ai_module.parse_tailored_tex(reply)
    assert parsed is not None
    assert parsed["tailored_tex"] == "\\documentclass{article}\nHi"


async def test_tailor_tex_retries_then_502_when_markers_missing(
    client, register, make_group, make_company, upload_tex, set_application,
    configure_ai, monkeypatch,
):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"])
    resume = await upload_tex(account["headers"])
    await set_application(
        account["headers"], company["id"], status="applied",
        resume_id=resume["id"], jd_text="Python",
    )
    await configure_ai(account["headers"])
    app_id = await _app_id(client, account["headers"], group["id"])

    # Marker present but no \documentclass both times -> retry once -> 502.
    bad = "===TAILORED_TEX===\nno document class here\n===END==="
    calls = _mock_reply(monkeypatch, bad, bad)
    resp = await client.post(
        f"/api/applications/{app_id}/tailor",
        json={"resume_id": resume["id"]},
        headers=account["headers"],
    )
    assert resp.status_code == 502
    assert calls["count"] == 2


# ---------------------------------------------------------------------------
# Advice path (pdf/docx)
# ---------------------------------------------------------------------------


async def _advice_setup(
    client, register, make_group, make_company, upload_docx, set_application,
    configure_ai, resume_body, jd_text,
):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"])
    resume = await upload_docx(account["headers"], body=resume_body)
    await set_application(
        account["headers"], company["id"],
        status="applied", resume_id=resume["id"], jd_text=jd_text,
    )
    await configure_ai(account["headers"])
    app_id = await _app_id(client, account["headers"], group["id"])
    return account, resume, app_id


# ---------------------------------------------------------------------------
# Deterministic skill backstop (advice branch): a suggested rewrite must never
# introduce a skill the resume lacks, even if the model tries to.
# ---------------------------------------------------------------------------


async def test_backstop_drops_suggestion_that_adds_unlisted_skill(
    client, register, make_group, make_company, upload_docx, set_application,
    configure_ai, monkeypatch,
):
    # Resume has Azure (not AWS); the JD wants AWS.
    account, resume, app_id = await _advice_setup(
        client, register, make_group, make_company, upload_docx, set_application,
        configure_ai, resume_body="Azure Python developer",
        jd_text="We need AWS, Python, and Azure.",
    )
    reply = json.dumps(
        {"suggestions": [
            # Fabricates AWS -> must be dropped by the backstop.
            {"section": "Skills", "original": "Azure",
             "suggested": "experience with AWS", "reason": "match the JD"},
            # Reuses only existing skills -> must be kept.
            {"section": "Summary", "original": "developer",
             "suggested": "Python developer", "reason": "sharper"}],
         "keywords_to_add": []}
    )
    _mock_reply(monkeypatch, reply)

    resp = await client.post(
        f"/api/applications/{app_id}/tailor",
        json={"resume_id": resume["id"]},
        headers=account["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "advice"
    # The fabricating suggestion is gone; only the safe rephrase remains.
    assert len(body["suggestions"]) == 1
    assert body["suggestions"][0]["suggested"] == "Python developer"
    assert all("AWS" not in s["suggested"] for s in body["suggestions"])
    # The dropped-but-JD-wanted skill is surfaced honestly as a gap.
    assert "AWS" in body["keywords_to_add"]


async def test_backstop_keeps_rephrase_using_existing_skills(
    client, register, make_group, make_company, upload_docx, set_application,
    configure_ai, monkeypatch,
):
    account, resume, app_id = await _advice_setup(
        client, register, make_group, make_company, upload_docx, set_application,
        configure_ai, resume_body="Azure Python developer", jd_text="Azure and Python.",
    )
    suggestion = {
        "section": "Summary", "original": "developer",
        "suggested": "Experienced developer skilled in Azure and Python",
        "reason": "aligns with the JD",
    }
    _mock_reply(monkeypatch, json.dumps({"suggestions": [suggestion], "keywords_to_add": []}))

    resp = await client.post(
        f"/api/applications/{app_id}/tailor",
        json={"resume_id": resume["id"]},
        headers=account["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["suggestions"] == [suggestion]  # kept unchanged


async def test_backstop_trims_covered_skills_from_keywords(
    client, register, make_group, make_company, upload_docx, set_application,
    configure_ai, monkeypatch,
):
    account, resume, app_id = await _advice_setup(
        client, register, make_group, make_company, upload_docx, set_application,
        configure_ai, resume_body="Azure developer", jd_text="AWS and Azure.",
    )
    # The model lists Azure (already on the resume) and AWS (a real gap).
    _mock_reply(
        monkeypatch,
        json.dumps({"suggestions": [], "keywords_to_add": ["Azure", "AWS"]}),
    )

    resp = await client.post(
        f"/api/applications/{app_id}/tailor",
        json={"resume_id": resume["id"]},
        headers=account["headers"],
    )
    assert resp.status_code == 200, resp.text
    keywords = resp.json()["keywords_to_add"]
    assert "Azure" not in keywords  # already covered, not a gap
    assert "AWS" in keywords


async def test_tailor_docx_returns_advice_suggestions(
    client, register, make_group, make_company, upload_docx, set_application,
    configure_ai, monkeypatch,
):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"])
    resume = await upload_docx(account["headers"])
    await set_application(
        account["headers"], company["id"],
        status="applied", resume_id=resume["id"],
        jd_text="We need Python and Docker.",
    )
    await configure_ai(account["headers"])
    app_id = await _app_id(client, account["headers"], group["id"])

    reply = json.dumps(
        {"suggestions": [
            {"section": "Summary", "original": "developer",
             "suggested": "backend developer", "reason": "matches the JD"}],
         # A genuine gap (not in the default resume body), so it survives the
         # backstop's covered-skill trim.
         "keywords_to_add": ["Kubernetes"]}
    )
    _mock_reply(monkeypatch, reply)

    resp = await client.post(
        f"/api/applications/{app_id}/tailor",
        json={"resume_id": resume["id"]},
        headers=account["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "advice"
    assert body["suggestions"][0] == {
        "section": "Summary", "original": "developer",
        "suggested": "backend developer", "reason": "matches the JD",
    }
    assert body["keywords_to_add"] == ["Kubernetes"]


# ---------------------------------------------------------------------------
# 409 prerequisite cases
# ---------------------------------------------------------------------------


async def test_tailor_409_without_ai_settings(
    client, register, make_group, make_company, upload_tex, set_application, monkeypatch,
):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"])
    resume = await upload_tex(account["headers"])
    await set_application(
        account["headers"], company["id"],
        status="applied", resume_id=resume["id"], jd_text="Python",
    )
    app_id = await _app_id(client, account["headers"], group["id"])
    resp = await client.post(
        f"/api/applications/{app_id}/tailor",
        json={"resume_id": resume["id"]},
        headers=account["headers"],
    )
    assert resp.status_code == 409
    assert "Configure your AI provider" in resp.json()["detail"]


async def test_tailor_409_without_jd(
    client, register, make_group, make_company, upload_tex, set_application, configure_ai,
):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"])
    resume = await upload_tex(account["headers"])
    await set_application(
        account["headers"], company["id"], status="applied", resume_id=resume["id"]
    )
    await configure_ai(account["headers"])
    app_id = await _app_id(client, account["headers"], group["id"])
    resp = await client.post(
        f"/api/applications/{app_id}/tailor",
        json={"resume_id": resume["id"]},
        headers=account["headers"],
    )
    assert resp.status_code == 409
    assert "job description" in resp.json()["detail"].lower()


async def test_tailor_409_when_resume_not_mine(
    client, register, make_group, make_company, set_application, configure_ai,
):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"])
    await set_application(account["headers"], company["id"], status="applied", jd_text="Python")
    await configure_ai(account["headers"])
    app_id = await _app_id(client, account["headers"], group["id"])
    resp = await client.post(
        f"/api/applications/{app_id}/tailor",
        json={"resume_id": 999999},
        headers=account["headers"],
    )
    assert resp.status_code == 409
    assert "resume" in resp.json()["detail"].lower()


async def test_tailor_404_when_application_not_mine(
    client, register, make_group, make_company, upload_tex, set_application, configure_ai,
):
    owner = await register(username="haris")
    group = await make_group(owner["headers"])
    company = await make_company(owner["headers"], group["id"])
    resume = await upload_tex(owner["headers"])
    await set_application(
        owner["headers"], company["id"], status="applied", resume_id=resume["id"],
        jd_text="Python",
    )
    app_id = await _app_id(client, owner["headers"], group["id"])

    # A stranger who is not even in the group cannot tailor this application.
    stranger = await register(username="mallory")
    await configure_ai(stranger["headers"])
    resp = await client.post(
        f"/api/applications/{app_id}/tailor",
        json={"resume_id": resume["id"]},
        headers=stranger["headers"],
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Malformed JSON -> retry once -> 502
# ---------------------------------------------------------------------------


async def test_tailor_retries_once_on_bad_json_then_succeeds(
    client, register, make_group, make_company, upload_tex, set_application,
    configure_ai, monkeypatch,
):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"])
    resume = await upload_tex(account["headers"])
    await set_application(
        account["headers"], company["id"], status="applied",
        resume_id=resume["id"], jd_text="Python",
    )
    await configure_ai(account["headers"])
    app_id = await _app_id(client, account["headers"], group["id"])

    good = _tex_reply("\\documentclass{article}", [])
    calls = _mock_reply(monkeypatch, "here is your resume, no markers at all", good)

    resp = await client.post(
        f"/api/applications/{app_id}/tailor",
        json={"resume_id": resume["id"]},
        headers=account["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["kind"] == "tex"
    assert calls["count"] == 2  # first bad, retried, second good


async def test_tailor_502_when_json_never_valid(
    client, register, make_group, make_company, upload_tex, set_application,
    configure_ai, monkeypatch,
):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"])
    resume = await upload_tex(account["headers"])
    await set_application(
        account["headers"], company["id"], status="applied",
        resume_id=resume["id"], jd_text="Python",
    )
    await configure_ai(account["headers"])
    app_id = await _app_id(client, account["headers"], group["id"])

    calls = _mock_reply(monkeypatch, "not json at all", "still not json")
    resp = await client.post(
        f"/api/applications/{app_id}/tailor",
        json={"resume_id": resume["id"]},
        headers=account["headers"],
    )
    assert resp.status_code == 502
    assert calls["count"] == 2  # tried once, retried once, then gave up


async def test_tailor_502_when_provider_errors(
    client, register, make_group, make_company, upload_tex, set_application,
    configure_ai, monkeypatch,
):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"])
    resume = await upload_tex(account["headers"])
    await set_application(
        account["headers"], company["id"], status="applied",
        resume_id=resume["id"], jd_text="Python",
    )
    await configure_ai(account["headers"])
    app_id = await _app_id(client, account["headers"], group["id"])

    async def fake(**kwargs):
        raise ai_module.AIError("Your API key was rejected")

    monkeypatch.setattr(ai_module, "chat_completion", fake)
    resp = await client.post(
        f"/api/applications/{app_id}/tailor",
        json={"resume_id": resume["id"]},
        headers=account["headers"],
    )
    assert resp.status_code == 502
    assert "rejected" in resp.json()["detail"]
