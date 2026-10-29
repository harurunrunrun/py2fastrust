The sources under `py2fastrust/vendor/ac_library_python/` come from
[ac-library-python](https://github.com/not522/ac-library-python), pinned to
commit `27fdbb71cd0d566bdeb12746db59c9d908c6b5d5`. Its CC0-1.0 license is retained
in that directory. `UPSTREAM.json` records each original Git blob identifier;
the bundled source bytes are unchanged. These sources are parsed as compiler
inputs and are also packaged for the browser converter.

The bundled `py2fastrust/stdlib/heapq.py` and `bisect.py` are adapted from
CPython 3.14.4. Optional C accelerators and the heapq doctest entry point were
removed; the Python algorithm implementations are preserved.

`py2fastrust/stdlib/__future__.py` is copied from the official CPython 3.14.4
standard library to preserve feature constants and release metadata. It uses
the same PSF license retained alongside the other bundled modules.

They retain the Python Software Foundation license in
`py2fastrust/stdlib/PYTHON_LICENSE.txt`. Generated general-runtime Rust files
include that license alongside the MIT runtime notice.

The high-accuracy error-function and gamma-function algorithms in
`py2fastrust/runtime/math.rs` are adapted from CPython's PSF-licensed
`Modules/mathmodule.c`. Source versions and attribution are recorded in that
file. The same PSF license is included in generated general-runtime Rust.

The floating-point quotient and remainder helpers in
`py2fastrust/runtime/float_arithmetic.rs` and `py2fastrust/native_scalar.py`
are adapted from `float_rem` and
`_float_div_mod` in
[CPython 3.14's Objects/floatobject.c](https://github.com/python/cpython/blob/v3.14.0/Objects/floatobject.c).
They use the same retained PSF license, included in generated Rust containing
these helpers.

Type-parameter collection and substitution control flow in
`py2fastrust/runtime/generic_alias.rs` is adapted from CPython 3.14's
`Objects/genericaliasobject.c`, `Objects/typevarobject.c`, and `Lib/typing.py`.
The source comments identify the upstream functions. These adaptations use the
same retained PSF license, including its notice in generated Rust submissions.

The frozenset hash mixer in `py2fastrust/runtime/frozenset.rs` is adapted from
`_shuffle_bits` and `frozenset_hash_impl` in
[CPython 3.14.4's Objects/setobject.c](https://github.com/python/cpython/blob/v3.14.4/Objects/setobject.c).
It uses the same retained PSF license, whose notice is included in generated Rust
containing this runtime code.

Docstring indentation handling in `py2fastrust/compiler.py` and
`py2fastrust/runtime/dynamic.rs` is adapted from `_PyCompile_CleanDoc` in
[CPython 3.14.4's Python/compile.c](https://github.com/python/cpython/blob/v3.14.4/Python/compile.c).
These routines retain blank lines while removing common indentation and use
the same bundled PSF license.

Native generated output includes the PSF license when its retained helpers
contain the CPython-derived `native_float_divmod` implementation. It includes
the Unicode license when retained number-parser or string-representation
tables contain Unicode data. Unicode dependencies are selected even with
`--no-optimize`; selecting Unicode semantics alone does not retain data or its
license. The full Unicode notice appears immediately before the first retained
table, and later tables explicitly refer to it. Numeric table entries share
lines. Other notices follow the components actually present in the output.
Using the official `ast` and `symtable` APIs in the compiler
does not by itself embed Python code in a generated program.
The repository LICENSE grants an output permission for original generated
runtime helpers; they do not require the project's copyright or MIT notice in
generated programs. The selected license for translated program logic does not
replace notices required for included third-party components.

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
these tables. The integer parser's and native scalar parser's Unicode
decimal-digit ranges use the same Unicode data.

`py2fastrust/runtime/normalization_tables.rs` contains Unicode 16.0 NFKD
decompositions, canonical combining classes and composition pairs, generated
from CPython 3.14's `unicodedata` by `tools/generate_normalization.py`. These
normalization data use the same Unicode License V3; the normalization algorithm
implementation is original MIT-licensed code.

Unicode names in `py2fastrust/runtime/unicode_names_tables.rs` are generated by
`tools/generate_unicode_names.py` from CPython 3.14's Unicode 16.0 `unicodedata`
names and lookup behavior. The 477 formal aliases are taken from the pinned
[Unicode 16.0 NameAliases.txt](https://www.unicode.org/Public/16.0.0/ucd/NameAliases.txt),
bundled with its upstream notices in `py2fastrust/unicode/`.
These names use the same Unicode License V3. Hangul and algorithmic character
ranges are represented separately; named sequences are excluded from Python
literal escape decoding. `tools/generate_unicode_names.py --check` checks the
alias source checksum, all aliases against CPython, and table reproducibility.

## Generated program license texts

License texts for translated program logic are bundled in
`py2fastrust/licenses/`. Run `pytors --list-licenses` for the available canonical
identifiers. The original three license texts have the following provenance:

- `CC0-1.0.txt` is copied from Debian's `/usr/share/common-licenses/CC0-1.0`.
  Its complete legal text has been checked against the
  [official CC0 1.0 legal code](https://creativecommons.org/publicdomain/zero/1.0/legalcode.en).
- `Unlicense.txt` contains the canonical text from [unlicense.org](https://unlicense.org/),
  including its final “For more information” line.
- `MIT.txt` uses the same permission and disclaimer as the repository's MIT license,
  with its copyright line crediting the authors of the original Python source.

Sources for additional license templates, including upstream and SPDX links,
are recorded in `py2fastrust/licenses/NOTICE.txt` alongside the bundled catalog.
Replaceable copyright fields credit the original Python source's authors;
copyright notices belonging to the license text itself are retained.

If the original Python source specifies a license, that license takes precedence.
Otherwise, the selected text applies to translated program logic. Bundled runtime and
third-party components retain their own MIT, PSF, and Unicode notices.

Dictionary entry-hash preservation and copy/merge paths in
`py2fastrust/runtime/keywords.rs` follow `dict_dict_merge` and `copy_lock_held`
from [CPython 3.14.4's Objects/dictobject.c](https://github.com/python/cpython/blob/v3.14.4/Objects/dictobject.c).
The implementation retains the distinct clone conditions and known-hash paths
so keyword-key comparison and hashing effects are preserved. These adaptations
use the PSF license retained in `py2fastrust/stdlib/PYTHON_LICENSE.txt`; generated
general-runtime Rust includes that full license with the runtime notice.

The execution phase ordering in `py2fastrust/runtime/execution.rs` and the
shared function constructor in `py2fastrust/runtime/builtin_hooks.rs` follow
CPython 3.14.4's `run_eval_code_obj` (`Python/pythonrun.c`), `PyEval_EvalCode`
(`Python/ceval.c`), `_PyFunction_FromConstructor`, and `PyFunction_NewWithQualName`
(`Objects/funcobject.c`).
These sources are distributed under the PSF license included in
`py2fastrust/stdlib/PYTHON_LICENSE.txt` and in generated Rust source notices.
