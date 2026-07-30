"""LaTeX compile endpoint: graceful 501 when tectonic is absent, 422 on a bad
document, and the success path that stores a new PDF resume with source_tex.
Plus the untrusted-mode hardening and the pre-compile denylist that blocks
file-input/output LaTeX before tectonic runs (local-file exfiltration).
No real tectonic binary is required - the compiler and denylist are pure logic."""

import subprocess
from pathlib import Path

import pytest

import app.latex as latex_module
import app.routers.resumes as resumes_router
from app.latex import (
    DENYLIST_MESSAGE,
    CompileError,
    assert_tex_allowed,
    compile_tex,
    find_forbidden_command,
    find_tectonic,
    strip_tex_comments,
)
from app.models import Resume

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
SAMPLE_TEX = "\\documentclass{article}\\begin{document}Hello\\end{document}"


async def test_compile_501_when_tectonic_absent(client, register, monkeypatch):
    account = await register(username="haris")
    monkeypatch.setattr(resumes_router, "find_tectonic", lambda: None)
    resp = await client.post(
        "/api/resumes/compile",
        json={"tex_source": SAMPLE_TEX, "label": "Compiled CV"},
        headers=account["headers"],
    )
    assert resp.status_code == 501
    detail = resp.json()["detail"]
    assert "not available" in detail
    assert "Overleaf" in detail


async def test_compile_422_on_bad_latex(client, register, monkeypatch):
    account = await register(username="haris")
    monkeypatch.setattr(resumes_router, "find_tectonic", lambda: "tectonic")

    def boom(tex_source, tectonic_path):
        raise CompileError("! Undefined control sequence.\nl.3 \\badcmd")

    monkeypatch.setattr(resumes_router, "compile_tex", boom)
    resp = await client.post(
        "/api/resumes/compile",
        json={"tex_source": SAMPLE_TEX, "label": "Compiled CV"},
        headers=account["headers"],
    )
    assert resp.status_code == 422
    assert "Undefined control sequence" in resp.json()["detail"]


async def test_compile_success_stores_pdf_resume_with_source(
    client, register, monkeypatch, asgi_app
):
    account = await register(username="haris")
    monkeypatch.setattr(resumes_router, "find_tectonic", lambda: "tectonic")
    monkeypatch.setattr(resumes_router, "compile_tex", lambda tex, path: PDF_BYTES)

    resp = await client.post(
        "/api/resumes/compile",
        json={"tex_source": SAMPLE_TEX, "label": "Compiled CV"},
        headers=account["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "pdf"
    assert body["label"] == "Compiled CV"
    assert body["size_bytes"] == len(PDF_BYTES)

    # It is a real resume row that retained the LaTeX source.
    async with asgi_app.state.sessionmaker() as session:
        row = await session.get(Resume, body["id"])
        assert row.kind == "pdf"
        assert row.source_tex == SAMPLE_TEX

    # And it serves as a normal resume file.
    served = await client.get(
        f"/api/resumes/{body['id']}/file", headers=account["headers"]
    )
    assert served.status_code == 200
    assert served.content == PDF_BYTES


async def test_compile_requires_auth(client):
    resp = await client.post(
        "/api/resumes/compile", json={"tex_source": SAMPLE_TEX, "label": "x"}
    )
    assert resp.status_code == 401


def test_find_tectonic_returns_none_when_unconfigured_and_absent(monkeypatch):
    monkeypatch.delenv("TECTONIC_PATH", raising=False)
    monkeypatch.setattr(latex_module.shutil, "which", lambda _name: None)
    assert find_tectonic() is None


# ---------------------------------------------------------------------------
# Untrusted-mode hardening (DEFECT 1): the .tex is attacker-controlled, so
# tectonic must always run with --untrusted + TECTONIC_UNTRUSTED_MODE=1 so a
# \input of a local file (e.g. data/.secret) cannot be embedded into the PDF.
# ---------------------------------------------------------------------------


def test_compile_runs_tectonic_in_untrusted_mode(monkeypatch):
    recorded = {}

    def fake_run(args, **kwargs):
        recorded["args"] = list(args)
        recorded["env"] = kwargs.get("env", {})
        # Simulate tectonic emitting the PDF into the build directory.
        Path(kwargs["cwd"], "resume.pdf").write_bytes(PDF_BYTES)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(latex_module.subprocess, "run", fake_run)
    out = compile_tex(SAMPLE_TEX, "tectonic")
    assert out == PDF_BYTES
    assert "--untrusted" in recorded["args"]
    assert recorded["env"].get("TECTONIC_UNTRUSTED_MODE") == "1"


# ---------------------------------------------------------------------------
# Pre-compile DENYLIST (DEFECT 1, real mitigation): --untrusted alone does NOT
# stop \input of an absolute-path file, so file-I/O LaTeX is rejected before
# tectonic ever runs. Regex-level tests, no binary needed.
# ---------------------------------------------------------------------------


def _wrap(snippet: str) -> str:
    return "\\documentclass{article}\\begin{document}" + snippet + "\\end{document}"


DENIED_SNIPPETS = [
    "\\input{secret.tex}",
    "\\include{part}",
    "\\subfile{x}",
    "\\subfileinclude{x}",
    "\\import{dir}{x}",
    "\\subimport{dir}{x}",
    "\\includestandalone{x}",
    "\\InputIfFileExists{x}{}{}",
    "\\openin1=secret",
    "\\openout1=out.txt",
    "\\read1 to \\x",
    "\\readline1 to \\x",
    "\\write16{leak}",
    "\\write18{ls}",
    "\\immediate\\write18{ls}",
    "\\immediate\\openout1=out.txt",
    "\\lstinputlisting{x}",
    "\\verbatiminput{x}",
    "\\VerbatimInput{x}",
    "\\inputminted{python}{x}",
    "\\includegraphics{x}",
    "\\special{dvi}",
    "\\catcode`\\%=12",
    "\\csname input\\endcsname",
    # Absolute-path \input: the exact payload --untrusted fails to block.
    "\\input{/etc/hostname}",
    "\\input{C:/Users/x/data/.secret}",
]


@pytest.mark.parametrize("snippet", DENIED_SNIPPETS)
def test_denylist_rejects_file_io_commands(snippet):
    with pytest.raises(CompileError) as excinfo:
        assert_tex_allowed(_wrap(snippet))
    assert excinfo.value.detail == DENYLIST_MESSAGE


ALLOWED_DOCS = [
    # A normal ATS-friendly resume: none of these are file-I/O commands.
    "\\documentclass{article}\\usepackage{geometry}\\section{Experience}"
    "\\textbf{Engineer}\\begin{itemize}\\item Built things\\end{itemize}\\end{document}",
    # inputenc appears as package-name TEXT (no backslash), so it is allowed.
    "\\documentclass{article}\\usepackage[utf8]{inputenc}\\begin{document}Hi\\end{document}",
    # graphicx package load is fine; only \includegraphics is blocked.
    "\\documentclass{article}\\usepackage{graphicx}\\begin{document}Hi\\end{document}",
    # A commented-out \input is stripped before the check, so it is allowed.
    "% \\input{secret}\n\\documentclass{article}\\begin{document}Clean\\end{document}",
    # A lone \immediate (not paired with write/openout) stays usable.
    "\\documentclass{article}\\begin{document}\\immediate\\relax Hi\\end{document}",
]


@pytest.mark.parametrize("doc", ALLOWED_DOCS)
def test_denylist_allows_normal_resume(doc):
    assert_tex_allowed(doc)  # must not raise


def test_denylist_catches_command_after_escaped_percent():
    # \% is a literal percent, NOT a comment start, so the \input after it is
    # live and must be caught (no hiding a command behind an escaped percent).
    doc = _wrap("\\%\\input{secret}")
    with pytest.raises(CompileError):
        assert_tex_allowed(doc)


def test_inputxyz_is_not_flagged_as_input():
    # A longer control word that merely starts with a denied name is fine.
    assert find_forbidden_command("\\inputxyz{ok}") is None
    # The boundary also lets a denied name appear as plain package-arg text.
    assert find_forbidden_command("\\usepackage{inputenc}") is None


def test_strip_tex_comments_keeps_escaped_percent():
    assert strip_tex_comments("a \\% b % comment") == "a \\% b "
    # A real comment line is removed; the following live line is kept.
    assert strip_tex_comments("% \\input{x}\n\\section{Real}") == "\n\\section{Real}"


async def test_compile_endpoint_rejects_file_input_with_422(client, register, monkeypatch):
    account = await register(username="haris")
    # tectonic "present" so we reach compile; the denylist (not tectonic) rejects.
    monkeypatch.setattr(resumes_router, "find_tectonic", lambda: "tectonic")
    resp = await client.post(
        "/api/resumes/compile",
        json={"tex_source": _wrap("\\input{/etc/hostname}"), "label": "CV"},
        headers=account["headers"],
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == DENYLIST_MESSAGE


def test_compile_concurrency_is_bounded():
    """DEFECT 2: simultaneous 60s compiles are capped so the threadpool cannot
    be exhausted; extra callers wait on the semaphore rather than piling up."""
    assert resumes_router.MAX_CONCURRENT_COMPILES == 2
    # A fresh semaphore admits exactly MAX_CONCURRENT_COMPILES holders.
    assert resumes_router._COMPILE_SEMAPHORE._value <= resumes_router.MAX_CONCURRENT_COMPILES
