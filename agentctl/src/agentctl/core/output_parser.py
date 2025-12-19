"""Output parsing utilities for cleaning tmux output and extracting prompts."""

import re
from dataclasses import dataclass
from typing import List, Optional


# ANSI escape sequence pattern
ANSI_PATTERN = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[()][AB012]')

# Patterns for detecting Claude Code prompts
PROMPT_QUESTION_PATTERN = re.compile(r'^\s*Do you want to (.+)\?')
PROMPT_OPTION_PATTERN = re.compile(r'^\s*[>]?\s*(\d+)\.\s+(.+)$')
SELECTED_OPTION_PATTERN = re.compile(r'^\s*[>❯]\s*(\d+)\.')


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


def extract_prompt(lines: List[str]) -> Optional[PromptInfo]:
    """Extract prompt information from Claude Code output.

    Detects prompts like:
      Do you want to create test.py?
      > 1. Yes
        2. Yes, allow all edits...
        3. Type here...

    Args:
        lines: Lines from tmux output

    Returns:
        PromptInfo if a prompt is detected, None otherwise
    """
    question = None
    options = []
    selected_index = 0

    for line in lines:
        # Check for question
        q_match = PROMPT_QUESTION_PATTERN.match(line)
        if q_match:
            question = f"Do you want to {q_match.group(1)}?"
            continue

        # Check for option
        opt_match = PROMPT_OPTION_PATTERN.match(line)
        if opt_match:
            option_num = int(opt_match.group(1))
            option_text = opt_match.group(2).strip()

            # Truncate long options
            if len(option_text) > 50:
                option_text = option_text[:47] + "..."

            options.append(option_text)

            # Check if this option is selected
            if SELECTED_OPTION_PATTERN.match(line):
                selected_index = option_num - 1

    if question and options:
        return PromptInfo(
            question=question,
            options=options,
            selected_index=selected_index
        )

    return None
