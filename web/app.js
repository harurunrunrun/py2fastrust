// Browser UI only. All translation and source directives belong to the worker.
export function createConverter(document, {
  createWorker = () => new Worker(new URL('./worker.mjs', import.meta.url), { type: 'module' }),
} = {}) {
  const elements = Object.fromEntries([
    'converter', 'integer', 'string-mode', 'license', 'optimize', 'convert', 'cancel', 'retry',
    'source', 'output', 'output-note', 'editors', 'status', 'diagnostics', 'diagnostic-list',
  ].map((id) => [id, document.getElementById(id)]));
  let worker = null;
  let state = 'cancelled';
  let sequence = 0;
  let revision = 0;
  let active = null;
  let hasMetadata = false;
  let outputRevision = null;

  function setStatus(message) {
    elements.status.textContent = message;
  }

  function render() {
    const busy = state === 'loading' || state === 'converting';
    elements.convert.disabled = state !== 'ready';
    elements.cancel.hidden = !busy;
    elements.retry.hidden = state !== 'failed' && state !== 'cancelled';
    elements.retry.textContent = state === 'cancelled' ? 'Load Python' : 'Retry loading';
    for (const control of [elements.integer, elements['string-mode'], elements.license, elements.optimize]) {
      control.disabled = !hasMetadata;
    }
    elements.editors.setAttribute('aria-busy', String(busy));
  }

  function showDiagnostics(diagnostics = []) {
    const rows = diagnostics.map((diagnostic) => {
      const row = document.createElement('li');
      let position = diagnostic.filename || 'main.py';
      if (diagnostic.line != null) position += `:${diagnostic.line}`;
      if (diagnostic.column != null) position += `:${diagnostic.column}`;
      const code = diagnostic.code ? ` [${diagnostic.code}]` : '';
      row.textContent = `${position}${code}: ${diagnostic.message || 'Conversion failed.'}`;
      return row;
    });
    elements['diagnostic-list'].replaceChildren(...rows);
    elements.diagnostics.hidden = rows.length === 0;
  }

  function releaseWorker() {
    if (worker) worker.terminate();
    worker = null;
    active = null;
  }

  function fail(message, diagnostics = []) {
    releaseWorker();
    state = 'failed';
    setStatus(`Error: ${message}`);
    showDiagnostics(diagnostics);
    render();
  }

  function populateOptions(metadata) {
    const integers = metadata?.integer_modes;
    const strings = metadata?.string_modes;
    const licenses = metadata?.licenses;
    if (![integers, strings, licenses].every((values) => Array.isArray(values) && values.length > 0
      && values.every((value) => typeof value === 'string' && value.length > 0))) {
      throw new Error('The converter returned incomplete option metadata.');
    }
    const defaults = metadata.defaults || {};
    for (const [control, values, fallback] of [
      [elements.integer, integers, defaults.integer || 'i64'],
      [elements['string-mode'], strings, defaults.string_mode || 'ascii'],
      [elements.license, licenses, defaults.license || 'CC0-1.0'],
    ]) {
      const selected = hasMetadata && values.includes(control.value) ? control.value : fallback;
      control.replaceChildren(...values.map((value) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = control === elements['string-mode']
          ? ({ ascii: 'ASCII', unicode: 'Unicode' }[value] || value) : value;
        return option;
      }));
      control.value = values.includes(selected) ? selected : values[0];
    }
    if (!hasMetadata) elements.optimize.checked = defaults.optimize !== false;
    hasMetadata = true;
  }

  function receive(sender, event) {
    const message = event.data;
    if (sender !== worker || !active || !message || message.id !== active.id) return;
    if (message.type === 'status') {
      setStatus(message.message || (state === 'loading' ? 'Loading Python…' : 'Converting…'));
      return;
    }
    if (message.type === 'ready' && active.type === 'init') {
      try {
        populateOptions(message.metadata);
      } catch (error) {
        fail(error.message);
        return;
      }
      active = null;
      state = 'ready';
      setStatus('Ready.');
      showDiagnostics();
      render();
    } else if (message.type === 'result' && active.type === 'convert') {
      const resultRevision = active.revision;
      const result = message.result || {};
      active = null;
      state = 'ready';
      if (resultRevision !== revision) {
        setStatus('Source or options changed. Convert again to update the Rust output.');
      } else if (result.rust_source == null && result.diagnostics?.length) {
        showDiagnostics(result.diagnostics);
        setStatus('Error: Conversion failed. See diagnostics below.');
      } else if (typeof result.rust_source !== 'string') {
        setStatus('Error: The converter returned no Rust source.');
      } else {
        elements.output.value = result.rust_source;
        outputRevision = revision;
        elements['output-note'].textContent = 'Generated Rust source is read-only.';
        showDiagnostics(result.diagnostics || []);
        setStatus(result.diagnostics?.length ? 'Conversion finished with diagnostics.' : 'Conversion complete.');
      }
      render();
    } else if (message.type === 'error') {
      if (active.type === 'init') {
        fail(message.error || 'Python could not be loaded.');
      } else {
        const resultRevision = active.revision;
        active = null;
        state = 'ready';
        if (resultRevision !== revision) {
          setStatus('Source or options changed. Convert again to update the Rust output.');
        } else {
          setStatus(`Error: ${message.error || 'Conversion failed.'}`);
        }
        render();
      }
    }
  }

  function initialize() {
    if (state === 'loading' || state === 'converting') return;
    releaseWorker();
    state = 'loading';
    setStatus('Loading Python…');
    showDiagnostics();
    render();
    try {
      const sender = createWorker();
      worker = sender;
      active = { id: ++sequence, type: 'init' };
      sender.addEventListener('message', (event) => receive(sender, event));
      sender.addEventListener('error', (event) => {
        if (sender !== worker) return;
        event.preventDefault?.();
        fail(event.message || 'The Python worker stopped unexpectedly.');
      });
      sender.addEventListener('messageerror', () => {
        if (sender === worker) fail('The Python worker returned an unreadable message.');
      });
      sender.postMessage({ id: active.id, type: 'init' });
    } catch (error) {
      fail(error.message || 'This browser could not start the Python worker.');
    }
  }

  function convert() {
    if (state !== 'ready' || !worker) return;
    state = 'converting';
    active = { id: ++sequence, type: 'convert', revision };
    setStatus('Converting…');
    showDiagnostics();
    render();
    try {
      worker.postMessage({
        id: active.id,
        type: 'convert',
        source: elements.source.value,
        options: {
          integer: elements.integer.value,
          string_mode: elements['string-mode'].value,
          license: elements.license.value,
          optimize: elements.optimize.checked,
        },
      });
    } catch (error) {
      fail(error.message || 'The conversion request could not be sent.');
    }
  }

  function changed() {
    revision += 1;
    if (outputRevision !== null && outputRevision !== revision) {
      elements['output-note'].textContent = 'Previous result. Convert to update the Rust output.';
    }
    if (state === 'ready') {
      showDiagnostics();
      setStatus('Source or options changed. Ready to convert.');
    }
  }

  elements.converter.addEventListener('submit', (event) => {
    event.preventDefault();
    convert();
  });
  elements.cancel.addEventListener('click', () => {
    if (state !== 'loading' && state !== 'converting') return;
    releaseWorker();
    state = 'cancelled';
    setStatus('Cancelled. Choose Load Python to prepare the converter again.');
    showDiagnostics();
    render();
  });
  elements.retry.addEventListener('click', initialize);
  elements.source.addEventListener('input', changed);
  elements.source.addEventListener('keydown', (event) => {
    if (!event.isComposing && event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      convert();
    }
  });
  for (const control of [elements.integer, elements['string-mode'], elements.license, elements.optimize]) {
    control.addEventListener('change', changed);
  }
  initialize();
}

if (typeof document !== 'undefined') createConverter(document);
