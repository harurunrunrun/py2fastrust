The bundled `py2fastrust/stdlib/heapq.py` and `bisect.py` are adapted from
CPython 3.14.4. Optional C accelerators and the heapq doctest entry point were
removed; the Python algorithm implementations are preserved.

They retain the Python Software Foundation license in
`py2fastrust/stdlib/PYTHON_LICENSE.txt`. Generated general-runtime Rust files
include that license alongside the MIT runtime notice.

The high-accuracy error-function and gamma-function algorithms in
`py2fastrust/runtime/math.rs` are adapted from CPython's PSF-licensed
`Modules/mathmodule.c`. Source versions and attribution are recorded in that
file. The same PSF license is included in generated general-runtime Rust.

The compiler uses the host Python's official `ast` and `symtable` APIs.
The Rust PEG engine and tokenizer are independent implementations. Its grammar
tables are generated from CPython 3.14.4's unmodified `Grammar/python.gram` and
`Grammar/Tokens`, retained in `py2fastrust/grammar/` with upstream blob identifiers
and a PSF license notice. `tools/generate_peg.py --check` checks both the pinned
source bytes and reproducibility of the generated Rust tables.

Unicode case-fold mappings and character-property ranges in
`py2fastrust/runtime/text.rs` are generated from CPython 3.14's Unicode 16.0
behavior by `tools/generate_unicode.py`. Unicode character data is covered by
the [Unicode License V3](https://www.unicode.org/license.txt), retained in
`py2fastrust/stdlib/UNICODE_LICENSE.txt` and in generated Rust that includes
these tables. The integer parser's Unicode decimal-digit ranges use the same
Unicode data.
