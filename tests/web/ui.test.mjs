import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import test from 'node:test';

const root = new URL('../../', import.meta.url);
const [app, html, css, licenseFiles] = await Promise.all([
  readFile(new URL('web/app.js', root), 'utf8'),
  readFile(new URL('web/index.html', root), 'utf8'),
  readFile(new URL('web/style.css', root), 'utf8'),
  readdir(new URL('py2fastrust/licenses/', root)),
]);
// app.js is a browser ES module; this import keeps the repository free of a
// package.json or a DOM dependency solely for these UI interaction tests.
const { createConverter } = await import(`data:text/javascript;base64,${Buffer.from(app).toString('base64')}`);
const metadata = {
  integer_modes: ['i64', 'i128', 'bigint'],
  string_modes: ['ascii', 'unicode'],
  licenses: licenseFiles.filter((name) => name.endsWith('.txt') && name !== 'NOTICE.txt')
    .map((name) => name.slice(0, -4)).sort(),
  defaults: { integer: 'i64', string_mode: 'ascii', license: 'CC0-1.0', optimize: true },
};

class Element {
  constructor(tagName, id = '') {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.value = '';
    this.textContent = '';
    this.hidden = false;
    this.disabled = false;
    this.checked = false;
    this.children = [];
    this.attributes = new Map();
    this.listeners = new Map();
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  emit(type, properties = {}) {
    const event = { type, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...properties };
    for (const listener of this.listeners.get(type) || []) listener(event);
    return event;
  }

  setAttribute(name, value) {
    this.attributes.set(name, value);
  }

  replaceChildren(...children) {
    this.children = children;
  }
}

class FakeDocument {
  constructor() {
    this.elements = new Map([...html.matchAll(/<([a-z][a-z0-9]*)\b[^>]*\bid="([^"]+)"[^>]*>/gi)]
      .map(([, tagName, id]) => [id, new Element(tagName, id)]));
    this.getElementById('source').value = 'print(1 + 2)\n';
    this.getElementById('integer').value = 'i64';
    this.getElementById('string-mode').value = 'ascii';
    this.getElementById('license').value = 'CC0-1.0';
    this.getElementById('optimize').checked = true;
  }

  getElementById(id) {
    const element = this.elements.get(id);
    assert.ok(element, `index.html must contain #${id}`);
    return element;
  }

  createElement(tagName) {
    return new Element(tagName);
  }
}

class FakeWorker extends Element {
  constructor() {
    super('worker');
    this.messages = [];
    this.terminated = false;
  }

  postMessage(message) {
    this.messages.push(structuredClone(message));
  }

  terminate() {
    this.terminated = true;
  }

  reply(message) {
    this.emit('message', { data: message });
  }
}

function setup({ startReady = true, createWorker } = {}) {
  const document = new FakeDocument();
  const workers = [];
  createConverter(document, { createWorker: createWorker || (() => {
    const worker = new FakeWorker();
    workers.push(worker);
    return worker;
  }) });
  const element = (id) => document.getElementById(id);
  const ready = (worker = workers.at(-1), options = metadata) => {
    worker.reply({ id: worker.messages.at(-1).id, type: 'ready', metadata: options });
  };
  if (startReady) ready();
  const submit = () => element('converter').emit('submit');
  const result = (rust = 'fn main() {}\n', diagnostics = [], worker = workers.at(-1), id = worker.messages.at(-1).id) => {
    worker.reply({ id, type: 'result', result: { rust_source: rust, diagnostics } });
  };
  return { document, workers, element, ready, submit, result };
}

test('starts one worker, waits for readiness, and uses the package option catalog', () => {
  const ui = setup({ startReady: false });
  const worker = ui.workers[0];
  assert.deepEqual(worker.messages, [{ id: 1, type: 'init' }]);
  assert.equal(ui.element('convert').disabled, true);
  assert.equal(ui.element('integer').disabled, true);
  assert.equal(ui.element('string-mode').disabled, true);
  assert.equal(ui.element('editors').attributes.get('aria-busy'), 'true');
  worker.reply({ id: 0, type: 'ready', metadata });
  assert.equal(ui.element('convert').disabled, true);
  worker.reply({ id: 1, type: 'status', message: 'Loading the converter package…' });
  assert.equal(ui.element('status').textContent, 'Loading the converter package…');
  ui.ready();
  assert.equal(ui.element('convert').disabled, false);
  assert.equal(ui.element('integer').disabled, false);
  assert.equal(ui.element('status').textContent, 'Ready.');
  assert.deepEqual(ui.element('integer').children.map((item) => item.value), metadata.integer_modes);
  assert.deepEqual(ui.element('license').children.map((item) => item.value), metadata.licenses);
  assert.deepEqual(ui.element('string-mode').children.map((item) => item.value), metadata.string_modes);
  assert.equal(ui.element('string-mode').value, 'ascii');
  assert.equal(ui.element('string-mode').disabled, false);
  assert.equal(ui.element('license').value, 'CC0-1.0');
  assert.equal(ui.element('optimize').checked, true);
});

test('only the integer option is shown until advanced options are opened', () => {
  const details = html.match(/<details\b([^>]*)>([\s\S]*?)<\/details>/);
  assert.ok(details, 'Additional options must have a disclosure control.');
  assert.match(details[1], /\bid="advanced-options"/);
  assert.doesNotMatch(details[1], /\bopen(?:\s|=|$)/, 'Advanced options must start closed.');
  assert.match(details[2], /<summary>Advanced options<\/summary>/);
  for (const id of ['string-mode', 'license', 'optimize']) {
    assert.match(details[2], new RegExp(`\\bid="${id}"`), `${id} must be inside advanced options.`);
  }
  assert.doesNotMatch(details[2], /\bid="(?:integer|convert)"/);
  const visibleMarkup = html.replace(details[0], '');
  assert.deepEqual([...visibleMarkup.matchAll(/<(?:select|input)\b[^>]*\bid="([^"]+)"/g)]
    .map(([, id]) => id), ['integer']);

  const ui = setup();
  ui.submit();
  assert.deepEqual(ui.workers[0].messages.at(-1).options, {
    integer: 'i64', string_mode: 'ascii', license: 'CC0-1.0', optimize: true,
  }, 'The closed advanced section must retain the converter defaults.');
});

test('conversion failures display the complete concrete cause and inert source text', () => {
  const ui = setup();
  ui.submit();
  const message = "Cannot lower call 's.replace': the native callable/member adapter has no implementation for this callee. "
    + "Types: receiver=str. Source: 's.replace(\"<img src=x>\",\"x\")'.";
  ui.result(null, [{ filename: 'main.py', line: 2, column: 7, code: 'E006', message }]);
  assert.equal(ui.element('diagnostics').hidden, false);
  const rows = ui.element('diagnostic-list').children;
  assert.equal(rows.length, 1);
  assert.equal(rows[0].textContent, `main.py:2:7 [E006]: ${message}`);
  assert.equal(rows[0].children.length, 0, 'Source snippets must remain text, including HTML-like input.');
  assert.equal(ui.element('convert').disabled, false, 'A missing native feature must allow another conversion.');
  assert.equal(ui.workers[0].terminated, false);
  ui.element('source').value = 'print(42)\n';
  ui.element('source').emit('input');
  ui.submit();
  ui.result('fn main() { println!("42"); }\n');
  assert.equal(ui.element('diagnostics').hidden, true);
  assert.equal(ui.element('status').textContent, 'Conversion complete.');
});

test('sends source as data, blocks duplicate submissions, and reuses its worker', () => {
  const ui = setup();
  const worker = ui.workers[0];
  const source = '# pytors: --int bigint --license Unlicense\nprint("${untrusted}")\n';
  ui.element('source').value = source;
  ui.element('source').emit('input');
  ui.element('integer').value = 'i128';
  ui.element('string-mode').value = 'unicode';
  ui.element('license').value = 'MIT';
  ui.element('optimize').checked = false;
  assert.equal(ui.submit().defaultPrevented, true);
  assert.deepEqual(worker.messages[1], {
    id: 2, type: 'convert', source,
    options: { integer: 'i128', string_mode: 'unicode', license: 'MIT', optimize: false },
  });
  ui.submit();
  assert.equal(worker.messages.length, 2);
  assert.equal(ui.element('convert').disabled, true);
  worker.reply({ id: 1, type: 'result', result: { rust_source: 'stale', diagnostics: [] } });
  assert.equal(ui.element('output').value, '');
  ui.result();
  assert.equal(ui.element('output').value, 'fn main() {}\n');
  assert.equal(ui.element('status').textContent, 'Conversion complete.');
  ui.submit();
  assert.equal(ui.workers.length, 1);
  assert.equal(worker.messages[2].id, 3);
  worker.reply({ id: 2, type: 'status', message: 'stale status' });
  assert.equal(ui.element('status').textContent, 'Converting…');
});

test('ignores a result after source or options change and identifies previous output', () => {
  for (const changed of ['source', 'integer', 'string-mode', 'license', 'optimize']) {
    const ui = setup();
    ui.submit();
    ui.result('previous output');
    ui.submit();
    const control = ui.element(changed);
    if (changed === 'source') control.value = 'print(42)\n';
    else if (changed === 'optimize') control.checked = false;
    else control.value = changed === 'integer' ? 'bigint' : changed === 'string-mode' ? 'unicode' : 'MIT';
    control.emit(changed === 'source' ? 'input' : 'change');
    ui.result('outdated output');
    assert.equal(ui.element('output').value, 'previous output', changed);
    assert.match(ui.element('output-note').textContent, /Previous result/, changed);
    assert.match(ui.element('status').textContent, /changed.*Convert again/, changed);
    assert.equal(ui.element('convert').disabled, false);
    ui.submit();
    ui.result('current output');
    assert.equal(ui.element('output').value, 'current output', changed);
    assert.equal(ui.element('output-note').textContent, 'Generated Rust source is read-only.');
  }
});

test('renders positioned diagnostics as text and retains the previous Rust output', () => {
  const ui = setup();
  ui.submit();
  ui.result('previous Rust');
  ui.element('source').value = 'if:\n';
  ui.element('source').emit('input');
  ui.submit();
  ui.result(null, [
    { filename: 'main.py', line: 1, column: 3, code: 'E001', message: '<img src=x onerror=alert(1)>' },
    { filename: 'helper.py', line: null, column: null, code: '', message: 'Module not found.' },
  ]);
  assert.equal(ui.element('output').value, 'previous Rust');
  assert.equal(ui.element('diagnostics').hidden, false);
  assert.deepEqual(ui.element('diagnostic-list').children.map((row) => row.textContent), [
    'main.py:1:3 [E001]: <img src=x onerror=alert(1)>',
    'helper.py: Module not found.',
  ]);
  assert.equal(ui.element('diagnostic-list').children[0].children.length, 0);
  assert.match(ui.element('status').textContent, /^Error: Conversion failed/);
  assert.equal(ui.element('convert').disabled, false);
  ui.element('source').emit('input');
  assert.equal(ui.element('diagnostics').hidden, true);
});

test('cancels without clearing editors and rejects messages from the terminated worker', () => {
  const ui = setup();
  const oldWorker = ui.workers[0];
  ui.submit();
  ui.result('preserved Rust');
  ui.element('integer').value = 'bigint';
  ui.element('string-mode').value = 'unicode';
  ui.element('license').value = 'MIT';
  ui.element('optimize').checked = false;
  ui.submit();
  ui.element('cancel').emit('click');
  assert.equal(oldWorker.terminated, true);
  assert.equal(ui.element('output').value, 'preserved Rust');
  assert.equal(ui.element('source').value, 'print(1 + 2)\n');
  assert.equal(ui.element('retry').hidden, false);
  ui.element('retry').emit('click');
  const newWorker = ui.workers[1];
  assert.ok(newWorker.messages[0].id > oldWorker.messages.at(-1).id);
  oldWorker.reply({ id: newWorker.messages[0].id, type: 'ready', metadata });
  assert.equal(ui.element('convert').disabled, true);
  ui.ready(newWorker);
  assert.equal(ui.element('integer').value, 'bigint');
  assert.equal(ui.element('string-mode').value, 'unicode');
  assert.equal(ui.element('license').value, 'MIT');
  assert.equal(ui.element('optimize').checked, false);
  oldWorker.reply({ id: oldWorker.messages.at(-1).id, type: 'result', result: { rust_source: 'late result' } });
  assert.equal(ui.element('output').value, 'preserved Rust');
  assert.equal(ui.element('status').textContent, 'Ready.');
});

test('initialization can be cancelled and retried, and repeated retry clicks start one worker', () => {
  const ui = setup({ startReady: false });
  ui.element('cancel').emit('click');
  assert.equal(ui.workers[0].terminated, true);
  assert.equal(ui.element('retry').textContent, 'Load Python');
  ui.element('retry').emit('click');
  ui.element('retry').emit('click');
  assert.equal(ui.workers.length, 2);
  ui.ready();
  assert.equal(ui.element('convert').disabled, false);
});

test('initialization failures expose retry, including missing metadata and worker creation errors', () => {
  const ui = setup({ startReady: false });
  ui.workers[0].reply({ id: 1, type: 'error', error: 'The runtime download failed.' });
  assert.equal(ui.workers[0].terminated, true);
  assert.equal(ui.element('retry').textContent, 'Retry loading');
  assert.match(ui.element('status').textContent, /runtime download failed/);
  ui.element('retry').emit('click');
  ui.ready(ui.workers[1], {});
  assert.equal(ui.workers[1].terminated, true);
  assert.match(ui.element('status').textContent, /incomplete option metadata/);
  ui.element('retry').emit('click');
  ui.ready();
  assert.equal(ui.element('status').textContent, 'Ready.');

  const unsupported = setup({ startReady: false, createWorker() { throw new Error('Workers are unavailable.'); } });
  assert.match(unsupported.element('status').textContent, /Workers are unavailable/);
  assert.equal(unsupported.element('retry').hidden, false);
});

test('conversion exceptions permit another request; fatal worker failures require a new worker', () => {
  const ui = setup();
  const worker = ui.workers[0];
  ui.submit();
  ui.result('prior result');
  ui.submit();
  worker.reply({ id: worker.messages.at(-1).id, type: 'error', error: 'Conversion raised an exception.' });
  assert.match(ui.element('status').textContent, /Conversion raised an exception/);
  assert.equal(ui.element('convert').disabled, false);
  assert.equal(worker.terminated, false);
  assert.equal(ui.element('output').value, 'prior result');
  ui.submit();
  const event = worker.emit('error', { message: 'The worker stopped.' });
  assert.equal(event.defaultPrevented, true);
  assert.equal(worker.terminated, true);
  assert.equal(ui.element('retry').hidden, false);
  assert.equal(ui.element('output').value, 'prior result');
  ui.element('retry').emit('click');
  ui.ready();
  ui.workers[1].emit('messageerror');
  assert.equal(ui.workers[1].terminated, true);
  assert.match(ui.element('status').textContent, /unreadable message/);
});

test('keyboard conversion supports Ctrl and Command, with the same duplicate guard', () => {
  for (const modifier of ['ctrlKey', 'metaKey']) {
    const ui = setup();
    const ordinaryEnter = ui.element('source').emit('keydown', { key: 'Enter' });
    assert.equal(ordinaryEnter.defaultPrevented, false);
    assert.equal(ui.workers[0].messages.length, 1);
    const composingEnter = ui.element('source').emit('keydown', { key: 'Enter', [modifier]: true, isComposing: true });
    assert.equal(composingEnter.defaultPrevented, false);
    assert.equal(ui.workers[0].messages.length, 1);
    const shortcut = ui.element('source').emit('keydown', { key: 'Enter', [modifier]: true });
    assert.equal(shortcut.defaultPrevented, true);
    assert.equal(ui.workers[0].messages.length, 2);
    ui.element('source').emit('keydown', { key: 'Enter', [modifier]: true });
    assert.equal(ui.workers[0].messages.length, 2);
  }
});

test('the page provides labels and a read-only output with relative resource URLs and monochrome styling', () => {
  assert.match(html, /<html lang="en">/);
  assert.match(html, /<label for="source">Python source<\/label>/);
  assert.match(html, /<label for="output">Rust output<\/label>/);
  assert.match(html, /<textarea id="output"[^>]*\breadonly\b/);
  assert.match(html, /id="status"[^>]*role="status"[^>]*aria-live="polite"/);
  assert.match(html, /href="\.\/style\.css"/);
  assert.match(html, /src="\.\/app\.js"/);
  assert.match(app, /new URL\('\.\/worker\.mjs', import\.meta\.url\)/);
  assert.match(app, /type: 'module'/);
  assert.deepEqual([...new Set(css.match(/#[\da-f]{3,8}\b/gi))].sort(), ['#000', '#fff']);
  assert.doesNotMatch(css, /(?:linear|radial)-gradient|rgba?\(|hsla?\(|@import|url\(/i);
  assert.match(css, /:focus-visible\s*\{/);
  assert.match(css, /::selection\s*\{/);
  assert.match(css, /@media \(max-width: 700px\)/);
});
