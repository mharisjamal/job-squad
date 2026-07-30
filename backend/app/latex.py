"""LaTeX -> PDF compilation via Tectonic, isolated so it can degrade gracefully.

Tectonic is optional: many free hosts (Render's free tier) will not have it, so
the caller checks find_tectonic() first and returns a clean 501 when it is
absent rather than crashing. Compilation runs as a subprocess with an explicit
argument list (never a shell string), a hard timeout, and captured stderr, so a
malformed document produces a trimmed error message instead of a hung or dead
process.

Security (defense in depth; this is NOT a full sandbox):
  1. tectonic is always run in UNTRUSTED mode (`--untrusted` + TECTONIC_UNTRUSTED_MODE=1),
     which reliably blocks shell-escape / \\write18 (remote code execution).
  2. BUT --untrusted alone does NOT stop \\input of an ABSOLUTE-path file: a real
     tectonic 0.17 still embeds \\input{/abs/path/to/data/.secret} into the PDF.
     So a pre-compile DENYLIST (assert_tex_allowed) rejects file-input/output
     LaTeX commands BEFORE tectonic runs. Our compile takes one self-contained
     tex_source string, so it never legitimately needs to read/write other files;
     \\usepackage{...} (bundled packages) stays allowed.
  IMPORTANT: full safety for server-side compile requires OS-level sandboxing
  (container/seccomp/read-only FS). PRODUCTION SHIPS WITHOUT TECTONIC, so the
  compile endpoint 501s and users compile on Overleaf - the live app is not
  exposed. This denylist protects any operator who does install tectonic.
"""

import os
import re
import shutil
import subprocess  # noqa: S404 - list-args only, never shell=True (see below)
import tempfile
from pathlib import Path

COMPILE_TIMEOUT_SECONDS = 60
# The trailing chunk of compiler output shown to the user on a failed build.
STDERR_TAIL_CHARS = 2000

# The 422 message when the denylist rejects a document. Kept as a constant so the
# router and the tests share the exact wording.
DENYLIST_MESSAGE = (
    "This resume uses LaTeX commands that are not allowed for server-side compile "
    "(file input/output). Download the .tex and use Overleaf instead."
)

# File-input / file-output / obfuscation control sequences. Blocked as real
# control words (backslash + name + a non-letter boundary) so \inputxyz does not
# trip the \input rule while \input{...} and "\input " do. Case-sensitive, since
# TeX command names are. \write covers \write18 (shell-escape); --untrusted also
# blocks that at the engine level. \expandafter is deliberately NOT listed (far
# too common in real templates to block).
_DENIED_COMMANDS = (
    "input",
    "include",
    "subfile",
    "subfileinclude",
    "import",
    "subimport",
    "includestandalone",
    "InputIfFileExists",
    "openin",
    "openout",
    "read",
    "readline",
    "write",
    "lstinputlisting",
    "verbatiminput",
    "VerbatimInput",
    "inputminted",
    "includegraphics",
    "special",
    "catcode",  # main obfuscation primitive; no normal resume redefines catcodes
    "csname",  # can construct \input dynamically
)
_DENYLIST_RE = re.compile(r"\\(?:" + "|".join(_DENIED_COMMANDS) + r")(?![a-zA-Z])")
# \immediate is only dangerous paired with a write/openout (write/openout are
# already blocked outright, so this is belt-and-suspenders and leaves a lone
# \immediate usable).
_IMMEDIATE_WRITE_RE = re.compile(
    r"\\immediate(?![a-zA-Z])\s*\\(?:write|openout)(?![a-zA-Z])"
)
# A TeX comment: an unescaped % to end of line. A backslash-escaped percent (\%)
# is a literal and must NOT start a comment.
_TEX_COMMENT_RE = re.compile(r"(?<!\\)%.*")


class CompileError(Exception):
    """A LaTeX document failed to compile; `detail` is a trimmed stderr tail."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def strip_tex_comments(source: str) -> str:
    """Remove TeX comments (unescaped % to end of line) from a copy of the source.

    A backslash-escaped percent (\\%) is a literal and does NOT start a comment,
    so a command hidden after an escaped percent stays visible to the denylist.
    This can only over-keep text (a false rejection is safe); it can never let a
    live command slip past by mistaking it for a comment.
    """
    return _TEX_COMMENT_RE.sub("", source)


def find_forbidden_command(source: str) -> str | None:
    """Return the first denied file-I/O LaTeX command in the source, else None.

    Runs on comment-stripped text so commented-out code never triggers.
    """
    cleaned = strip_tex_comments(source)
    match = _DENYLIST_RE.search(cleaned)
    if match:
        return match.group(0)
    match = _IMMEDIATE_WRITE_RE.search(cleaned)
    if match:
        return match.group(0)
    return None


def assert_tex_allowed(source: str) -> None:
    """Reject dangerous LaTeX before it ever reaches tectonic.

    Raises CompileError (mapped to 422 by the router) so a malicious resume that
    tries to read or write local files is stopped at the door, independent of
    tectonic's own (incomplete) --untrusted protection.
    """
    if find_forbidden_command(source) is not None:
        raise CompileError(DENYLIST_MESSAGE)


def find_tectonic() -> str | None:
    """Locate the tectonic binary: TECTONIC_PATH first, then PATH. None if absent."""
    configured = os.environ.get("TECTONIC_PATH", "").strip()
    if configured and Path(configured).is_file():
        return configured
    return shutil.which("tectonic")


def compile_tex(tex_source: str, tectonic_path: str) -> bytes:
    """Compile LaTeX source to PDF bytes. Raises CompileError on any failure.

    The source is written into a throwaway temp directory and tectonic is asked
    to emit into that same directory; the process is never given a shell, and a
    timeout guards against a document that never terminates.
    """
    # Defense in depth: reject file-input/output LaTeX before tectonic runs, since
    # --untrusted does not block \input of an absolute-path file.
    assert_tex_allowed(tex_source)
    with tempfile.TemporaryDirectory(prefix="jobsquad-tex-") as tmp:
        tmp_path = Path(tmp)
        tex_file = tmp_path / "resume.tex"
        tex_file.write_text(tex_source, encoding="utf-8")
        args = [
            tectonic_path,
            # Untrusted input: no shell-escape, no reading files outside tmp_path,
            # no absolute paths. The .tex is attacker-controlled, so this is
            # mandatory (defends against \input{data/.secret} exfiltration).
            "--untrusted",
            "-o",
            str(tmp_path),
            "--chatter",
            "minimal",
            "--keep-logs",
            str(tex_file),
        ]
        # Belt-and-suspenders: the env var is tectonic's second lever for the
        # same protection, honored even where the CLI flag might not be.
        env = {**os.environ, "TECTONIC_UNTRUSTED_MODE": "1"}
        try:
            proc = subprocess.run(  # noqa: S603 - fixed args, no shell, trusted binary path
                args,
                capture_output=True,
                timeout=COMPILE_TIMEOUT_SECONDS,
                cwd=str(tmp_path),
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise CompileError(
                f"LaTeX compile timed out after {COMPILE_TIMEOUT_SECONDS}s."
            ) from exc
        except OSError as exc:
            raise CompileError("Could not run the LaTeX compiler.") from exc

        pdf_file = tmp_path / "resume.pdf"
        if proc.returncode != 0 or not pdf_file.is_file():
            stderr = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
            tail = stderr[-STDERR_TAIL_CHARS:] if stderr else "Compile failed with no output."
            raise CompileError(tail)
        return pdf_file.read_bytes()
