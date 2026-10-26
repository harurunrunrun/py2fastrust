#!/usr/bin/env python3
"""Rebuild std-only Unicode tables from the project's supported CPython 3.14."""

import argparse
from pathlib import Path
import sys
import unicodedata


START = "// BEGIN GENERATED UNICODE TABLES"
END = "// END GENERATED UNICODE TABLES"
TARGET = Path(__file__).resolve().parents[1] / "py2fastrust/runtime/text.rs"


def rust_string(value):
    return '"' + "".join(f"\\u{{{ord(char):x}}}" for char in value) + '"'


def ranges(predicate):
    output = []
    start = previous = None
    for codepoint in range(sys.maxunicode + 1):
        if predicate(chr(codepoint)):
            if start is None:
                start = codepoint
            previous = codepoint
        elif start is not None:
            output.append((start, previous))
            start = previous = None
    if start is not None:
        output.append((start, previous))
    return output


def generate():
    if sys.version_info[:2] != (3, 14):
        raise SystemExit("Generate Unicode tables using CPython 3.14")
    lines = [START, f'const TEXT_UNICODE_VERSION: &str = "{unicodedata.unidata_version}";',
             "const TEXT_CASEFOLD: &[(u32, &str)] = &["]
    for codepoint in range(sys.maxunicode + 1):
        source = chr(codepoint)
        target = source.casefold()
        if source != target:
            lines.append(f"    (0x{codepoint:x}, {rust_string(target)}),")
    lines.append("];")
    for name, predicate in [("DECIMAL", str.isdecimal), ("DIGIT", str.isdigit),
                            ("NUMERIC", str.isnumeric), ("SPACE", str.isspace),
                            ("PRINTABLE", str.isprintable), ("ALPHA", str.isalpha),
                            ("ALNUM", str.isalnum), ("LOWER", str.islower),
                            ("UPPER", str.isupper),
                            ("CASED", lambda ch: ch.islower() or ch.isupper() or ch.istitle()),
                            ("IDENTIFIER_START", str.isidentifier),
                            ("IDENTIFIER_CONTINUE", lambda ch: ("a" + ch).isidentifier())]:
        lines.append(f"const TEXT_{name}: &[(u32, u32)] = &[")
        for first, last in ranges(predicate):
            lines.append(f"    (0x{first:x}, 0x{last:x}),")
        lines.append("];")
    lines.append(END)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check that generated tables are current")
    options = parser.parse_args()
    source = TARGET.read_text(encoding="utf-8")
    before, rest = source.split(START, 1)
    _, after = rest.split(END, 1)
    result = before + generate() + after
    if options.check:
        if result != source:
            raise SystemExit("Unicode tables need regeneration")
    else:
        TARGET.write_text(result, encoding="utf-8")


if __name__ == "__main__":
    main()
