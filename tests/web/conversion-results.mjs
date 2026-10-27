// A rejected Python program is a conversion result, not a broken Pages build.
import assert from 'node:assert/strict';

export function currentWorkerResult(messages, boundary, requestId) {
  return messages.slice(boundary).find(message =>
    message.type === 'result' && message.id === requestId)?.result;
}

export function verifyConversionResult({ name, status, result, cli, output, previousOutput }) {
  assert.ifError(cli.error);
  assert.equal(cli.signal ?? null, null, `${name}: CLI was terminated`);
  assert(result && Array.isArray(result.diagnostics), `${name}: missing worker result`);
  if (/Conversion failed/.test(status)) {
    assert.equal(result.rust_source, null, `${name}: rejected conversion supplied Rust`);
    assert(result.diagnostics.length > 0, `${name}: rejection has no diagnostics`);
    assert.equal(cli.status, 2, `${name}: browser/CLI conversion outcome differs`);
    const expected = result.diagnostics.map(diagnostic =>
      `${diagnostic.filename}:${diagnostic.line}:${diagnostic.column}: ${diagnostic.code}: ${diagnostic.message}\n`).join('');
    assert.equal(cli.stderr, expected, `${name}: browser/CLI diagnostics differ`);
    assert.equal(cli.stdout, '', `${name}: rejected CLI emitted unexpected stdout`);
    assert.equal(output, previousOutput, `${name}: rejection replaced the previous output`);
    return { name, conversion: 'failed', cli_parity: true, standalone: false,
      diagnostics: result.diagnostics };
  }
  assert.equal(status, 'Conversion complete.', `${name}: unexpected browser status`);
  assert.equal(cli.status, 0, `${name}: CLI conversion failed\n${cli.stderr}`);
  assert.equal(typeof result.rust_source, 'string', `${name}: successful result has no Rust`);
  assert.equal(output, result.rust_source, `${name}: output differs from the worker result`);
  assert.deepEqual(result.diagnostics, [], `${name}: unexpected success diagnostics`);
  return { name, conversion: 'passed' };
}

export function conversionSummary(report) {
  const converted = report.cases.filter(item => item.conversion === 'passed').length;
  const rejected = report.cases.filter(item => item.conversion === 'failed');
  return {
    converted, conversion_failures: rejected.length,
    all_converted: report.cases.length > 0 && rejected.length === 0,
    markdown: `Browser verification: **${report.success ? 'passed' : 'failed'}**.\n\n`
      + `Converted examples: ${converted}. Recorded conversion failures: ${rejected.length}.\n\n`
      + rejected.map(item => `- ${item.name}: ${item.diagnostics.map(d => d.code).join(', ')}\n`).join('')
      + (rejected.length ? '\nConversion failures are recorded without blocking Pages deployment.\n' : ''),
  };
}
