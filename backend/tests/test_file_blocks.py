"""Tests for parsing delimited file output from the Developer agent.

Source code is emitted as delimited text rather than JSON because escaping code
into a JSON string is where models reliably produce malformed output.
"""

from app.agents.implementations import clip, parse_file_blocks


def test_parses_single_file():
    out = "### FILE: app/main.py\n```python\nprint('hi')\n```"
    assert parse_file_blocks(out) == [("app/main.py", "print('hi')\n")]


def test_parses_multiple_files_and_ignores_prose():
    out = (
        "Sure, here is the code.\n\n"
        "### FILE: app/main.py\n```python\napp = 1\n```\n\n"
        "And the models:\n\n"
        "### FILE: app/models.py\n```\nclass Task: pass\n```\n\nDone!"
    )
    assert [p for p, _ in parse_file_blocks(out)] == ["app/main.py", "app/models.py"]


def test_code_containing_quotes_and_braces_survives():
    """The exact content that breaks JSON-mode generation."""
    code = 'def f():\n    return {"status": "ok", "q": \'x\'}\n'
    out = f"### FILE: app/api.py\n```python\n{code}```"
    assert parse_file_blocks(out)[0][1].strip() == code.strip()


def test_stray_fence_does_not_leak_into_file():
    """A leftover fence turns a valid module into a first-line SyntaxError."""
    out = "### FILE: app/__init__.py\n```\n```\n```"
    files = parse_file_blocks(out)
    assert files, "block should still be recognised"
    assert "```" not in files[0][1]


def test_empty_file_is_allowed():
    out = "### FILE: app/__init__.py\n```python\n\n```"
    assert parse_file_blocks(out) == [("app/__init__.py", "")]


def test_rejects_absolute_and_traversal_paths():
    out = (
        "### FILE: ../../etc/passwd\n```\nevil\n```\n"
        "### FILE: /etc/shadow\n```\nevil\n```\n"
        "### FILE: app/ok.py\n```\nfine\n```"
    )
    assert [p for p, _ in parse_file_blocks(out)] == ["app/ok.py"]


def test_duplicate_paths_keep_first():
    out = "### FILE: a.py\n```\nfirst\n```\n### FILE: a.py\n```\nsecond\n```"
    files = parse_file_blocks(out)
    assert len(files) == 1
    assert files[0][1].strip() == "first"


def test_no_blocks_returns_empty_so_caller_can_fall_back():
    assert parse_file_blocks("I could not complete that request.") == []
    assert parse_file_blocks("") == []


def test_varied_heading_levels_accepted():
    assert parse_file_blocks("## FILE: a.py\n```\nx\n```")
    assert parse_file_blocks("#### FILE: a.py\n```\nx\n```")


# --- clip ----------------------------------------------------------------


def test_clip_leaves_short_text_untouched():
    assert clip("short", 100) == "short"


def test_clip_bounds_long_text_and_marks_the_gap():
    out = clip("x" * 10_000, 1000)
    assert len(out) < 1200
    assert "characters omitted" in out


def test_clip_handles_none_and_empty():
    assert clip("", 10) == ""
    assert clip(None, 10) == ""
