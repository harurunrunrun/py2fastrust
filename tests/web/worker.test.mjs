// Transport tests execute the real worker module with a simulated Pyodide loader.
// They do not prove browser or Python/WASM compatibility; browser.mjs does that.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';

const temporary = await mkdtemp(join(tmpdir(), 'pytors-worker-test-'));
await writeFile(join(temporary, 'pyodide.mjs'),
  'export const loadPyodide = options => globalThis.__pytorsTestLoader(options);\n');
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const pause = () => new Promise(resolve => setTimeout(resolve, 1));
let generation = 0;
async function harness({ invalidWheel = false, invalidBridge = false, production = false } = {}) {
  const messages = [], requests = [], conversions = [], files = new Map();
  const wheel = new TextEncoder().encode('verified wheel bytes');
  const bridge = new TextEncoder().encode('# verified bridge bytes');
  const commit = 'a'.repeat(40);
  const manifest = {
    schema_version: 1, preview: !production, source_commit: commit,
    pyodide: { version: '314.0.7', index_url: pathToFileURL(temporary + '/').href },
    wheel: { path: `assets/${commit}/py2fastrust-0.1.0a1-py3-none-any.whl`,
      size: wheel.length, sha256: invalidWheel ? '0'.repeat(64) : digest(wheel) },
    bridge: { path: 'bridge.py', sha256: invalidBridge ? '0'.repeat(64) : digest(bridge) },
  };
  let receive, loads = 0, installs = 0;
  globalThis.self = {
    postMessage(message) { messages.push(message); },
    addEventListener(type, handler) { assert.equal(type, 'message'); receive = handler; },
  };
  globalThis.fetch = async (url, options) => {
    assert.equal(options.credentials, 'omit');
    requests.push(String(url));
    if (String(url).endsWith('/web-manifest.json')) return Response.json(manifest);
    if (String(url).endsWith('.whl')) return new Response(wheel);
    if (String(url).endsWith('/bridge.py')) return new Response(bridge);
    return new Response('missing', { status: 404 });
  };
  globalThis.__pytorsTestLoader = async options => {
    assert.equal(options.indexURL, manifest.pyodide.index_url);
    loads++;
    return {
      version: '314.0.7', FS: {
        writeFile(path, bytes) { files.set(path, bytes); },
        unlink(path) { files.delete(path); },
      },
      globals: { set(name, value) { assert.equal(name, '_pytors_wheel'); assert.match(value, /^emfs:\/tmp\//); } },
      async loadPackage(name) { assert.equal(name, 'micropip'); },
      async runPythonAsync(code) {
        installs++;
        assert.equal(code, 'import micropip\nawait micropip.install(_pytors_wheel, deps=False)\ndel _pytors_wheel');
      },
      pyimport(name) {
        assert.equal(name, 'pytors_bridge');
        return {
          initialize(text) { assert.deepEqual(JSON.parse(text), manifest); return JSON.stringify({ string_modes: ['ascii', 'unicode'], defaults: { string_mode: 'ascii' } }); },
          convert(text) { conversions.push(JSON.parse(text)); return JSON.stringify({ rust_source: 'Rust', diagnostics: [] }); },
        };
      },
    };
  };
  await import(new URL(`../../web/worker.mjs?test=${++generation}`, import.meta.url));
  async function send(message) {
    receive({ data: message });
    for (let i = 0; i < 2000; i++) {
      const terminal = messages.find(m => m.id === message.id && ['ready', 'result', 'error'].includes(m.type));
      if (terminal) return terminal;
      await pause();
    }
    throw new Error('Worker did not complete the request.');
  }
  return { send, messages, requests, conversions, files, manifest,
    counts: () => ({ loads, installs }) };
}

test('verified wheel/bridge, serialized requests, reusable runtime and source-as-data', async () => {
  const h = await harness();
  const ready = await h.send({ id: 1, type: 'init' });
  assert.equal(ready.type, 'ready');
  assert.equal(ready.metadata.source_commit, 'a'.repeat(40));
  assert.deepEqual(ready.metadata.string_modes, ['ascii', 'unicode']);
  assert.equal(ready.metadata.defaults.string_mode, 'ascii');
  const source = 'raise RuntimeError("must not execute")\n</script>\n';
  const first = h.send({ id: 2, type: 'convert', source, options: { integer: 'bigint', string_mode: 'unicode' } });
  const second = h.send({ id: 3, type: 'convert', source: 'print(42)', options: {} });
  assert.equal((await first).type, 'result');
  assert.equal((await second).type, 'result');
  assert.deepEqual(h.counts(), { loads: 1, installs: 1 });
  assert.deepEqual(h.conversions, [{ source, options: { integer: 'bigint', string_mode: 'unicode' } }, { source: 'print(42)', options: {} }]);
  assert.equal(h.requests.length, 3);
  assert.deepEqual([...h.files.keys()], ['/home/pyodide/pytors_bridge.py']);
});

test('wheel corruption fails before installation and initialization can retry', async () => {
  const h = await harness({ invalidWheel: true });
  assert.match((await h.send({ id: 1, type: 'init' })).error, /wheel SHA-256/);
  assert.deepEqual(h.counts(), { loads: 1, installs: 0 });
  h.manifest.wheel.sha256 = digest(new TextEncoder().encode('verified wheel bytes'));
  assert.equal((await h.send({ id: 2, type: 'init' })).type, 'ready');
  assert.deepEqual(h.counts(), { loads: 2, installs: 1 });
});

test('bridge corruption fails before importing the converter', async () => {
  const h = await harness({ invalidBridge: true });
  assert.match((await h.send({ id: 1, type: 'init' })).error, /bridge SHA-256/);
  assert.equal(h.files.has('/home/pyodide/pytors_bridge.py'), false);
});

test('production manifests reject a runtime mirror', async () => {
  const h = await harness({ production: true });
  assert.match((await h.send({ id: 1, type: 'init' })).error, /pinned runtime/);
  assert.deepEqual(h.counts(), { loads: 0, installs: 0 });
});

test('manifest paths cannot escape the site directory', async () => {
  const h = await harness();
  h.manifest.wheel.path = `assets/${h.manifest.source_commit}/../../../../../../outside.whl`;
  assert.match((await h.send({ id: 1, type: 'init' })).error, /invalid asset path/);
  assert.equal(h.requests.length, 1);
  assert.equal(h.counts().installs, 0);
});
