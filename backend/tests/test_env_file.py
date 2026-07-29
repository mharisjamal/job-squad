"""Stdlib .env loading: parsing rules, file precedence, and env-wins-over-file."""

import os

from app.config import apply_env_files, parse_env_text, read_env_file

NEON_URL = (
    "postgresql://user:pass@ep-cool-123-pooler.eu-central-1.aws.neon.tech"
    "/jobsquad?sslmode=require&channel_binding=require"
)


def test_parses_simple_pairs():
    assert parse_env_text("A=1\nB=two\n") == {"A": "1", "B": "two"}


def test_ignores_blanks_and_comments():
    text = "\n# a comment\n\nA=1\n   # indented comment\nB=2\n"
    assert parse_env_text(text) == {"A": "1", "B": "2"}


def test_strips_whitespace_around_key_and_value():
    assert parse_env_text("  KEY  =   value  ") == {"KEY": "value"}


def test_strips_matching_quotes_only():
    parsed = parse_env_text(
        "\n".join(
            [
                'DOUBLE="quoted value"',
                "SINGLE='quoted value'",
                'MISMATCHED="unclosed',
                "INNER=say \"hi\" there",
            ]
        )
    )
    assert parsed["DOUBLE"] == "quoted value"
    assert parsed["SINGLE"] == "quoted value"
    assert parsed["MISMATCHED"] == '"unclosed'
    assert parsed["INNER"] == 'say "hi" there'


def test_ignores_export_prefix():
    assert parse_env_text("export A=1\nexport   B=2") == {"A": "1", "B": "2"}


def test_value_with_equals_and_ampersand_survives():
    """A Neon URL carries both, and must round-trip byte for byte."""
    parsed = parse_env_text(f"DATABASE_URL={NEON_URL}")
    assert parsed["DATABASE_URL"] == NEON_URL


def test_quoted_url_is_unquoted_intact():
    parsed = parse_env_text(f'DATABASE_URL="{NEON_URL}"')
    assert parsed["DATABASE_URL"] == NEON_URL


def test_malformed_lines_are_skipped_silently():
    parsed = parse_env_text("no_equals_here\n=novalue\n   \nGOOD=yes\n=\n")
    assert parsed == {"GOOD": "yes"}


def test_empty_value_is_allowed():
    assert parse_env_text("EMPTY=") == {"EMPTY": ""}


def test_read_missing_file_is_a_noop(tmp_path):
    assert read_env_file(tmp_path / "nope.env") == {}


def test_read_directory_does_not_raise(tmp_path):
    assert read_env_file(tmp_path) == {}


def test_apply_sets_only_absent_keys(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("JS_TEST_NEW=from_file\nJS_TEST_EXISTING=from_file\n")
    monkeypatch.setenv("JS_TEST_EXISTING", "from_real_env")
    monkeypatch.delenv("JS_TEST_NEW", raising=False)

    apply_env_files([env_file])

    # The real environment always wins; only the missing key is filled in.
    assert os.environ["JS_TEST_EXISTING"] == "from_real_env"
    assert os.environ["JS_TEST_NEW"] == "from_file"
    monkeypatch.delenv("JS_TEST_NEW", raising=False)


def test_later_file_wins_between_files(tmp_path, monkeypatch):
    root_env = tmp_path / ".env"
    backend_env = tmp_path / "backend.env"
    root_env.write_text("JS_TEST_ORDER=root\nJS_TEST_ROOT_ONLY=root\n")
    backend_env.write_text("JS_TEST_ORDER=backend\n")
    for name in ("JS_TEST_ORDER", "JS_TEST_ROOT_ONLY"):
        monkeypatch.delenv(name, raising=False)

    apply_env_files([root_env, backend_env])

    assert os.environ["JS_TEST_ORDER"] == "backend"
    assert os.environ["JS_TEST_ROOT_ONLY"] == "root"
    for name in ("JS_TEST_ORDER", "JS_TEST_ROOT_ONLY"):
        monkeypatch.delenv(name, raising=False)


def test_apply_with_no_existing_files_is_a_noop(tmp_path):
    apply_env_files([tmp_path / "a.env", tmp_path / "b.env"])  # must not raise


def test_database_url_from_file_reaches_settings(tmp_path, monkeypatch):
    from app.config import Settings

    env_file = tmp_path / ".env"
    env_file.write_text(f'DATABASE_URL="{NEON_URL}"\n')
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("JOBSQUAD_SECRET", "x")

    apply_env_files([env_file])
    try:
        assert Settings.load().database_url == NEON_URL
    finally:
        monkeypatch.delenv("DATABASE_URL", raising=False)
