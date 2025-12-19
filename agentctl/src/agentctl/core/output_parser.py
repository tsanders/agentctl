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


def collapse_whitespace(lines: List[str]) -> List[str]:
    """Collapse multiple blank lines and trim trailing whitespace.

    Args:
        lines: List of text lines

    Returns:
        Cleaned lines with collapsed whitespace
    """
    result = []
    prev_blank = False

    for line in lines:
        # Trim trailing whitespace (preserve leading)
        line = line.rstrip()
        is_blank = len(line) == 0

        # Skip consecutive blank lines
        if is_blank and prev_blank:
            continue

        result.append(line)
        prev_blank = is_blank

    # Remove trailing blank lines
    while result and result[-1] == "":
        result.pop()

    return result


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
