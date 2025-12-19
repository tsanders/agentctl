"""Output parsing utilities for cleaning tmux output and extracting prompts."""

import re
from dataclasses import dataclass
from typing import List, Optional


# ANSI escape sequence pattern
ANSI_PATTERN = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[()][AB012]')


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text.

    Args:
        text: Raw text potentially containing ANSI codes

    Returns:
        Clean text with all ANSI escape sequences removed
    """
    return ANSI_PATTERN.sub('', text)


@dataclass
class PromptInfo:
    """Extracted prompt information from Claude Code output."""
    question: str
    options: List[str]
    selected_index: int = 0


@dataclass
class ParsedOutput:
    """Cleaned and parsed output from a tmux pane."""
    raw_lines: List[str]
    clean_lines: List[str]
    prompt: Optional[PromptInfo] = None
