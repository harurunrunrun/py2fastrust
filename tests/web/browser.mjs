#!/usr/bin/env node
// Real Pyodide/module-worker verification. The submitted Python stays data.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createServer } from 'node:http';
import { mkdtemp, mkdir, readFile, realpath, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { extname, join, resolve, sep } from 'node:path';
import { parseArgs } from 'node:util';
import { pathToFileURL } from 'node:url';

const { values } = parseArgs({ options: {
  site: { type: 'string' }, source: { type: 'string', default: '.' },
  artifacts: { type: 'string', default: 'dist/browser-test' },
  'playwright-module': { type: 'string' }, python: { type: 'string', default: 'python3' },
} });
assert(values.site, 'Pass --site PATH to a built site directory.');
const source = resolve(values.source);
const site = await realpath(values.site);
const artifacts = resolve(values.artifacts);
await mkdir(artifacts, { recursive: true });
const { chromium } = await import(values['playwright-module']
  ? pathToFileURL(resolve(values['playwright-module'])).href : 'playwright');
const manifest = JSON.parse(await readFile(join(site, 'web-manifest.json'), 'utf8'));
const mime = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript',
  '.css': 'text/css', '.json': 'application/json', '.py': 'text/plain', '.wasm': 'application/wasm' };
const prefix = '/py2fastrust/';
const requests = [];
const server = createServer(async (request, response) => {
  try {
    const pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
    if (!pathname.startsWith(prefix)) { response.writeHead(404).end(); return; }
    const path = resolve(site, pathname.slice(prefix.length) || 'index.html');
    if (!path.startsWith(site + sep)) { response.writeHead(403).end(); return; }
    const bytes = await readFile(path);
    response.writeHead(200, { 'Content-Type': mime[extname(path)] || 'application/octet-stream' });
    response.end(bytes);
  } catch { response.writeHead(404).end(); }
});
await new Promise((resolve, reject) => {
  server.once('error', reject);
  server.listen(0, '127.0.0.1', resolve);
});
const origin = `http://127.0.0.1:${server.address().port}`;
let browser;
const report = { source_commit: manifest.source_commit, preview: manifest.preview,
  pyodide: manifest.pyodide.version, cases: [], success: false };
function run(command, args, options = {}) {
  const result = spawnSync(command, args, { encoding: 'utf8', timeout: 180_000,
    maxBuffer: 64 * 1024 * 1024, ...options });
  assert.equal(result.status, 0,
    `${command} failed: ${result.error || ''}\n${result.stdout || ''}\n${result.stderr || ''}`);
  return result.stdout;
}
try {
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1360, height: 1000 } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => {
    if (message.type() === 'error') errors.push(message.text());
  });
  context.on('request', request => requests.push({ url: request.url(), method: request.method() }));
  await page.addInitScript(() => {
    window.__workerMessages = [];
    window.__workerCount = 0;
    const OriginalWorker = window.Worker;
    window.Worker = class extends OriginalWorker {
      constructor(...args) {
        super(...args);
        window.__workerCount += 1;
        this.addEventListener('message', event => window.__workerMessages.push(event.data));
      }
    };
  });
  await page.goto(origin + prefix);
  await page.waitForFunction(() => {
    const status = document.getElementById('status').textContent;
    return status === 'Ready.' || status.startsWith('Error:');
  }, undefined, { timeout: 180_000 });
  assert.equal(await page.locator('#status').textContent(), 'Ready.');
  const ready = await page.evaluate(() => window.__workerMessages.find(m => m.type === 'ready'));
  assert(ready, 'The actual worker must report ready.');
  assert.deepEqual(ready.metadata.integer_modes, ['i64', 'i128', 'bigint']);
  assert.equal(ready.metadata.licenses.length, 20);
  assert.equal(ready.metadata.source_commit, manifest.source_commit);
  assert.equal(ready.metadata.wheel_sha256, manifest.wheel.sha256);
  assert.equal(ready.metadata.resource_count, manifest.resources.length);
  assert.deepEqual(ready.metadata.smoke_checks,
    { ast: true, symtable: true, compile: true, sha256: true, resources: true });
  const cliProfile = JSON.parse(run(values.python, ['-c',
    'import json; from py2fastrust.python_profile import profile; print(json.dumps(profile()))'], {
    env: { ...process.env, PYTHONPATH: source },
  }));
  assert.deepEqual(ready.metadata.python_profile, cliProfile,
    'Byte-for-byte parity requires the CLI and Pyodide to use the same Python patch compatibility profile.');
  report.runtime = ready.metadata;
  // All conversions below must finish with new network requests blocked.
  await context.route('**/*', route => route.abort('internetdisconnected'));
  const cases = [
    { name: 'default', source: 'print(1 + 2)\n', integer: 'i64', license: 'CC0-1.0', input: '' },
    { name: 'source-options', source: '# pytors: --int i128 --license Unlicense\nimport sys\nprint(2 ** 100)\n',
      integer: 'i64', license: 'MIT', input: '' },
    { name: 'bigint', source: 'print(10 ** 50 + 1)\n', integer: 'bigint', license: 'MIT', input: '' },
    { name: 'bfs', source: await readFile(join(source, 'examples/bfs.py'), 'utf8'),
      integer: 'i64', license: 'CC0-1.0', input: '5 3\n0 1\n1 2\n3 4\n' },
    { name: 'dynamic-unicode', source: 'print(eval("40 + 2"))\nprint(eval(r\'"\\N{GREEK SMALL LETTER LAMDA}"\'))\n',
      integer: 'i128', license: 'Unlicense', input: '', optimize: false },
    { name: 'source-is-data', source: 'raise RuntimeError("translation must not execute me")\n',
      integer: 'i64', license: 'CC0-1.0', compile: false },
    { name: 'html-is-data', source: 'print("</textarea><script>window.sourceWasExecuted = true</script>")\n',
      integer: 'i64', license: 'CC0-1.0', input: '' },
  ];
  for (const item of cases) {
    await page.locator('#source').fill(item.source);
    await page.locator('#integer').selectOption(item.integer);
    await page.locator('#license').selectOption(item.license);
    await page.locator('#optimize').setChecked(item.optimize !== false);
    await page.locator('#convert').click();
    await page.waitForFunction(() => !document.getElementById('convert').disabled, undefined, { timeout: 180_000 });
    assert.equal(await page.locator('#status').textContent(), 'Conversion complete.', item.name);
    const rust = await page.locator('#output').inputValue();
    const directory = await mkdtemp(join(tmpdir(), 'pytors-browser-'));
    await writeFile(join(directory, 'main.py'), item.source);
    const options = ['--int', item.integer, '--license', item.license];
    if (item.optimize === false) options.push('--no-optimize');
    run(values.python, ['-m', 'py2fastrust', 'main.py', '-o', 'main.rs', ...options], {
      cwd: directory, env: { ...process.env, PYTHONPATH: source },
    });
    assert.equal(rust, await readFile(join(directory, 'main.rs'), 'utf8'), `${item.name}: CLI parity`);
    assert(rust.includes('Transpilation does not use generative AI.'));
    if (item.compile !== false) {
      run('rustc', ['--edition=2021', '-O', join(directory, 'main.rs'), '-o', join(directory, 'main')]);
      const actual = run(join(directory, 'main'), [], { input: item.input, env: { PATH: '/nonexistent' } });
      const expected = run(values.python, [join(directory, 'main.py')], { input: item.input });
      assert.equal(actual, expected, `${item.name}: standalone Rust/CPython parity`);
    }
    assert.equal(await page.evaluate(() => window.sourceWasExecuted), undefined);
    report.cases.push({ name: item.name, cli_parity: true, standalone: item.compile !== false });
    if (item.name === 'bfs') await page.screenshot({ path: join(artifacts, 'desktop.png'), fullPage: true });
  }
  const previous = await page.locator('#output').inputValue();
  await page.locator('#source').fill('def broken(:\n');
  await page.locator('#convert').click();
  await page.waitForFunction(() => !document.getElementById('convert').disabled);
  assert.match(await page.locator('#status').textContent(), /Conversion failed/);
  assert.match(await page.locator('#diagnostic-list').textContent(), /main\.py:1:/);
  assert.equal(await page.locator('#output').inputValue(), previous);
  assert.equal(await page.evaluate(() => window.__workerCount), 1, 'Conversions must reuse the initialized worker.');
  await page.locator('#source').fill('print("keyboard")\n');
  await page.locator('#source').press('Control+Enter');
  await page.waitForFunction(() => document.getElementById('status').textContent === 'Conversion complete.');
  const style = await page.evaluate(() => {
    const colors = new Set();
    for (const element of document.querySelectorAll('*')) {
      const s = getComputedStyle(element);
      for (const property of ['color', 'backgroundColor', 'borderTopColor']) {
        if (s[property] !== 'rgba(0, 0, 0, 0)') colors.add(s[property]);
      }
    }
    const left = document.getElementById('source').getBoundingClientRect();
    const right = document.getElementById('output').getBoundingClientRect();
    return { colors: [...colors], sideBySide: left.x < right.x && left.y === right.y };
  });
  assert(style.sideBySide);
  assert(style.colors.every(c => ['rgb(0, 0, 0)', 'rgb(255, 255, 255)'].includes(c)), JSON.stringify(style.colors));
  await page.setViewportSize({ width: 390, height: 844 });
  assert(await page.evaluate(() => {
    const a = document.getElementById('source').getBoundingClientRect();
    const b = document.getElementById('output').getBoundingClientRect();
    return b.y > a.bottom && document.documentElement.scrollWidth <= innerWidth;
  }));
  await page.screenshot({ path: join(artifacts, 'mobile.png'), fullPage: true });
  assert.deepEqual(errors, [], 'No browser errors should occur.');
  const external = requests.filter(r => !r.url.startsWith(origin));
  assert(external.every(r => r.method === 'GET' && r.url.startsWith(manifest.pyodide.index_url)),
    'Only pinned runtime assets may be requested externally.');
  report.success = true;
  report.network_requests = requests;
  console.log(JSON.stringify({ success: true, cases: report.cases.length, source_commit: manifest.source_commit }));
} catch (error) {
  report.error = error.stack || String(error);
  throw error;
} finally {
  await writeFile(join(artifacts, 'report.json'), JSON.stringify(report, null, 2) + '\n');
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
}
