# Browser converter

The static interface uses plain HTML, CSS, and JavaScript. Its colors are black
and white. Python source appears on the left and read-only Rust output on the
right; narrow screens stack the editors. The converter runs in a module worker.

Paste a single Python file, choose an integer mode and license, and press
**Convert**. Ctrl+Enter or Command+Enter in the source editor also converts.
Leading `# pytors:` or `# py2fastrust:` directives take precedence over the
selected options, as they do in the core API. The worker supplies the available
integer modes and license identifiers from the installed package.

The status below the editors reports loading, readiness, conversion, or failure.
Diagnostics include the filename and available line/column positions. **Cancel**
stops the worker without clearing either editor. **Load Python** or **Retry
loading** starts a fresh worker. A loaded worker is reused for later conversions.
If the source or options change during conversion, that result is discarded;
press **Convert** again for the current input. Previous output is retained when
a request fails or is cancelled.

The page translates source; it does not compile or run the generated Rust.
Translation runs locally after the runtime and package assets have loaded.
The single source file is named `main.py`. Imports needing additional user files
are reported by the core converter.

The browser uses the same strict direct-Rust API as the CLI. **Optimize** controls
optional Rust helper pruning; unchecking it keeps direct generation enabled.
An unimplemented construct or type combination produces a positioned `E006`
diagnostic and retains the previous output. The converter never switches the
whole program to a general backend. Direct support for many language features
and library calls is still unfinished; the retained internal runtime is not an
alternate mode exposed by the page.

An existing license in the original Python source takes precedence. The license
selector supplies the generated file's fallback license; it does not replace
the original source's license. Generated attribution, license text, and the
commented original source are supplied by the same converter used by the CLI.

## Files and deployment paths

- `index.html`, `style.css`, and `app.js` are the interface.
- `worker.mjs` and `bridge.py` load and invoke the packaged Python converter.
- The build supplies `web-manifest.json` and a commit-addressed wheel asset.

Serve the generated build directory over HTTP, including its runtime files and
manifest. Opening `index.html` directly from the filesystem does not provide
the module-worker environment. Resource URLs resolve relative to the page and
worker so a project deployment at `/py2fastrust/` keeps that prefix.

## UI interaction checks

From the repository root, run:

```sh
node tests/web/ui.test.mjs
```

These dependency-free tests use a small DOM harness and a mocked worker to check
interface state, request identifiers, options, diagnostics, cancellation, retry,
and keyboard submission. They do not load Pyodide or validate Python-to-Rust
translation. Actual browser/runtime checks and core parity checks are separate.

## Build and verify

Use Python 3.14 with setuptools 77 or newer and wheel installed. A production
build exports a Git commit and builds the converter wheel from that snapshot:

```sh
python tools/build_web.py --output dist/web
```

The build rejects an incomplete wheel, hashes every package resource, and records
the full source commit in `web-manifest.json`. Uncommitted files are excluded.
For a local preview of edits, supply `--preview-source . --source-commit HASH`;
the resulting manifest explicitly records `preview: true` and source hashes.
The runtime is pinned to Pyodide 314.0.7 (Python 3.14). Its files load from
jsDelivr; the converter wheel and bridge come from the site's own directory.
The browser parity workflow uses Python 3.14.2 to match this Pyodide release.
The core test workflow separately covers Python 3.14.4 and the latest 3.14
release. Generated runtime metadata follows the converter host's observed patch
behavior; the browser test checks that both sides use the same profile before
comparing source bytes.

```sh
python -m unittest discover -s tests/web -p 'test_*.py' -v
node tests/web/ui.test.mjs
node tests/web/worker.test.mjs
npm install --no-save --ignore-scripts playwright@1.62.1
npx playwright install chromium
node tests/web/browser.mjs --site dist/web --source .
```

The last command starts a local HTTP server at the project prefix, loads the real
module worker in Chromium, and checks AST, symbol tables, compilation, SHA-256,
and wheel resources. It compares browser output byte for byte with the CLI,
compiles standalone Rust examples, compares their output with CPython, checks
diagnostics and keyboard input, and saves desktop/mobile screenshots. After
initialization, new network requests are blocked during conversion. This test
requires permission to start a local server and Chromium, and network access to
the pinned runtime assets. A UI mock test does not replace this gate.

## GitHub Pages

In the repository's **Settings → Pages**, select **GitHub Actions** as the build
source. Push the reviewed commits to `main` or run the **browser converter**
workflow manually. The workflow verifies the package, UI, and real browser before
uploading the exact build and deploying it. Pull requests run verification
without deploying. The expected project URL is
`https://harurunrunrun.github.io/py2fastrust/`; publication depends on the repository
Pages settings and a successful workflow. No site is published by a local build.
