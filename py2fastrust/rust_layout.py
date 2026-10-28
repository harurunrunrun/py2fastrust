"""Remove empty assembly gaps without touching Rust literals or comments."""

import re

from .rust_pruning import _lex, _Unsupported


_BLANK_RUN = re.compile(r"(?m)^[ \t]*\n(?:[ \t]*\n)+")


def compact_blank_lines(source: str) -> str:
    """Keep at most one blank line outside literal and comment contents.

    Helper pruning leaves the whitespace between discarded items behind. Rust
    raw strings, multiline strings and block comments can contain significant
    blank lines, so a global whitespace replacement would change the program.
    """
    try:
        tokens, comments, _pairs = _lex(source)
    except _Unsupported:
        return source
    protected = sorted(
        [(token.start, token.end) for token in tokens if token.kind == "literal"]
        + [(start, end) for start, end, _doc in comments]
    )
    edits = []
    cursor = 0
    for match in _BLANK_RUN.finditer(source):
        while cursor < len(protected) and protected[cursor][1] <= match.start():
            cursor += 1
        if cursor == len(protected) or protected[cursor][0] >= match.end():
            edits.append((match.start(), match.end()))
    parts = []
    start = 0
    for first, last in edits:
        parts.extend((source[start:first], "\n"))
        start = last
    parts.append(source[start:])
    return "".join(parts)
