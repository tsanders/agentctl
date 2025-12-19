"""Tests for output_parser module"""

import pytest
from agentctl.core.output_parser import strip_ansi, collapse_whitespace, ParsedOutput, PromptInfo, extract_prompt, parse_output, is_destructive_prompt


class TestStripAnsi:
    def test_removes_color_codes(self):
        text = "\x1b[32mgreen text\x1b[0m"
        assert strip_ansi(text) == "green text"

    def test_removes_cursor_movement(self):
        text = "\x1b[2J\x1b[H Hello"
        assert strip_ansi(text) == " Hello"

    def test_preserves_plain_text(self):
        text = "plain text without codes"
        assert strip_ansi(text) == "plain text without codes"

    def test_handles_multiple_codes(self):
        text = "\x1b[1m\x1b[31mbold red\x1b[0m normal"
        assert strip_ansi(text) == "bold red normal"


class TestCollapseWhitespace:
    def test_collapses_multiple_blank_lines(self):
        lines = ["line1", "", "", "", "line2"]
        assert collapse_whitespace(lines) == ["line1", "", "line2"]

    def test_trims_trailing_spaces(self):
        lines = ["text with trailing   ", "  leading and trailing  "]
        result = collapse_whitespace(lines)
        assert result == ["text with trailing", "  leading and trailing"]

    def test_removes_trailing_blank_lines(self):
        lines = ["content", "", ""]
        assert collapse_whitespace(lines) == ["content"]

    def test_handles_empty_input(self):
        assert collapse_whitespace([]) == []

    def test_handles_all_blank_lines(self):
        lines = ["", "", ""]
        assert collapse_whitespace(lines) == []


class TestExtractPrompt:
    def test_extracts_create_file_prompt(self):
        lines = [
            " Do you want to create test_auth.py?",
            " > 1. Yes",
            "   2. Yes, allow all edits during this session (shift+tab)",
            "   3. Type here to tell Claude what to do differently",
            "",
            " Esc to cancel",
        ]
        prompt = extract_prompt(lines)
        assert prompt is not None
        assert prompt.question == "Do you want to create test_auth.py?"
        assert len(prompt.options) == 3
        assert prompt.options[0] == "Yes"
        assert prompt.selected_index == 0

    def test_extracts_edit_file_prompt(self):
        lines = [
            " Do you want to edit src/main.py?",
            "   1. Yes",
            " > 2. Yes, allow all edits during this session",
            "   3. Type here...",
        ]
        prompt = extract_prompt(lines)
        assert prompt is not None
        assert prompt.selected_index == 1

    def test_returns_none_for_no_prompt(self):
        lines = [
            "Running tests...",
            "====== 5 passed in 2.3s ======",
        ]
        prompt = extract_prompt(lines)
        assert prompt is None

    def test_extracts_bash_command_prompt(self):
        lines = [
            " Do you want to run this command?",
            " > 1. Yes",
            "   2. No",
        ]
        prompt = extract_prompt(lines)
        assert prompt is not None
        assert "run this command" in prompt.question


class TestParseOutput:
    def test_full_parsing_with_prompt(self):
        raw = """
\x1b[32m Some colored output\x1b[0m


 Do you want to create test.py?
 > 1. Yes
   2. No

 Esc to cancel
"""
        result = parse_output(raw, max_lines=4)

        assert len(result.clean_lines) <= 4
        assert result.prompt is not None
        assert result.prompt.question == "Do you want to create test.py?"

    def test_limits_output_lines(self):
        raw = "\n".join([f"line {i}" for i in range(100)])
        result = parse_output(raw, max_lines=4)

        assert len(result.clean_lines) == 4

    def test_prioritizes_prompt_in_output(self):
        raw = """
lots of build output here
more output
even more

 Do you want to proceed?
 > 1. Yes
   2. No
"""
        result = parse_output(raw, max_lines=4)

        # Should include the prompt, not just the first 4 lines
        assert result.prompt is not None
        assert any("proceed" in line.lower() or "yes" in line.lower()
                   for line in result.clean_lines)

    def test_handles_empty_input(self):
        result = parse_output("", max_lines=4)
        assert result.clean_lines == []
        assert result.prompt is None


class TestIsDestructivePrompt:
    def test_detects_delete(self):
        prompt = PromptInfo("Do you want to delete this file?", ["Yes", "No"], 0)
        assert is_destructive_prompt(prompt) is True

    def test_detects_remove(self):
        prompt = PromptInfo("Do you want to remove all data?", ["Yes", "No"], 0)
        assert is_destructive_prompt(prompt) is True

    def test_detects_overwrite(self):
        prompt = PromptInfo("Do you want to overwrite existing.py?", ["Yes", "No"], 0)
        assert is_destructive_prompt(prompt) is True

    def test_safe_prompt_returns_false(self):
        prompt = PromptInfo("Do you want to create test.py?", ["Yes", "No"], 0)
        assert is_destructive_prompt(prompt) is False
