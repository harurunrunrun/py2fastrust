import assert from 'node:assert/strict';
import { test } from 'node:test';
import { conversionSummary, currentWorkerResult, verifyConversionResult } from './conversion-results.mjs';

const diagnostic = { filename: 'main.py', line: 1, column: 7, code: 'E006', message: 'not implemented' };
function rejected(overrides = {}) {
  return { name: 'unsupported', status: 'Error: Conversion failed. See diagnostics below.',
    result: { rust_source: null, diagnostics: [diagnostic] },
    cli: { status: 2, stdout: '', stderr: 'main.py:1:7: E006: not implemented\n' },
    output: 'previous Rust', previousOutput: 'previous Rust', ...overrides };
}
function converted() {
  return { name: 'supported', status: 'Conversion complete.',
    result: { rust_source: 'new Rust', diagnostics: [] }, cli: { status: 0 },
    output: 'new Rust', previousOutput: 'previous Rust' };
}

test('each conversion requires a fresh response with the current request ID', () => {
  const old = { rust_source: null, diagnostics: [diagnostic] };
  const fresh = { rust_source: 'fresh Rust', diagnostics: [] };
  const messages = [{ type: 'result', id: 3, result: old },
    { type: 'result', id: 4, result: old }, { type: 'result', id: 5, result: fresh }];
  assert.equal(currentWorkerResult(messages, 1, 3), undefined);
  assert.equal(currentWorkerResult(messages, 2, 4), undefined);
  assert.equal(currentWorkerResult(messages, 1, 5), fresh);
  assert.throws(() => verifyConversionResult(rejected({
    result: currentWorkerResult(messages, 3, 6),
  })), /missing worker result/);
});

test('a conversion rejection is recorded and later examples are still checked', () => {
  const cases = [converted(), rejected(), converted()].map(verifyConversionResult);
  assert.deepEqual(cases.map(item => item.conversion), ['passed', 'failed', 'passed']);
  assert.equal(cases[1].standalone, false);
  assert.deepEqual(cases[1].diagnostics, [diagnostic]);
  const summary = conversionSummary({ success: true, cases });
  assert.equal(summary.converted, 2);
  assert.equal(summary.conversion_failures, 1);
  assert.equal(summary.all_converted, false);
  assert.match(summary.markdown, /without blocking Pages/);
});

test('syntax diagnostics are retained as conversion failures too', () => {
  const syntax = { ...diagnostic, code: 'E001', message: 'invalid syntax' };
  const result = verifyConversionResult(rejected({
    result: { rust_source: null, diagnostics: [syntax] },
    cli: { status: 2, stdout: '', stderr: 'main.py:1:7: E001: invalid syntax\n' },
  }));
  assert.equal(result.diagnostics[0].code, 'E001');
});

test('a rejection cannot compile stale output or hide a CLI disagreement', () => {
  for (const input of [
    rejected({ output: 'changed' }),
    rejected({ cli: { status: 0, stdout: '', stderr: '' } }),
    rejected({ cli: { status: 1, stdout: '', stderr: 'Traceback: internal crash\n' } }),
    rejected({ cli: { status: 2, stdout: '', stderr: 'Traceback: internal crash\n' } }),
    rejected({ result: { rust_source: 'fallback Rust', diagnostics: [diagnostic] } }),
  ]) assert.throws(() => verifyConversionResult(input));
});

test('worker, transport and process errors remain verifier failures', () => {
  for (const input of [
    rejected({ status: 'Error: worker unavailable' }),
    rejected({ result: null }),
    rejected({ cli: { status: null, error: new Error('spawn failed') } }),
    rejected({ cli: { status: null, signal: 'SIGTERM' } }),
    { ...converted(), cli: { status: 1, stderr: 'failed' } },
  ]) assert.throws(() => verifyConversionResult(input));
});

test('a complete report keeps successful conversion counts distinct from verification', () => {
  const summary = conversionSummary({ success: true, cases: [verifyConversionResult(converted())] });
  assert.equal(summary.all_converted, true);
  assert.equal(summary.conversion_failures, 0);
  assert.match(conversionSummary({ success: false, cases: [] }).markdown, /verification: \*\*failed/);
});
