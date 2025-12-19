"""Tests for output_parser module"""

import pytest
from agentctl.core.output_parser import strip_ansi, ParsedOutput, PromptInfo


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
