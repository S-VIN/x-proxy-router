"""Simplified patterns shared by server name filters and routing rules.

A pattern is compared with a whole string, ignoring case: * stands for any
characters, none included; every other character, the dot too, stands for itself.
"""

WILDCARD = "*"


def pattern_matches(pattern: str, text: str) -> bool:
    """Whether the whole text matches the pattern.

    Each part between wildcards is taken at its first occurrence, which leaves
    the most room for the parts after it, so the check never backtracks.
    """
    first, *parts = pattern.casefold().split(WILDCARD)
    text = text.casefold()
    if not parts:
        return text == first
    *middle, last = parts
    end = len(text) - len(last)
    if end < len(first) or not text.startswith(first) or not text.endswith(last):
        return False
    position = len(first)
    for part in middle:
        index = text.find(part, position, end)
        if index < 0:
            return False
        position = index + len(part)
    return True
