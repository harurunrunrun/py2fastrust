// Pyodide 314 requires an ES module worker. Keep Python source out of code strings.
export const PYODIDE_VERSION = "314.0.7";
export const PYODIDE_INDEX_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;

let runtimePromise;
let queued = Promise.resolve();

function status(id, message) {
  self.postMessage({ id, type: "status", message });
}

async function checkedFetch(url) {
  const response = await fetch(url, { credentials: "omit" });
  if (!response.ok) throw new Error(`Download failed (${response.status}): ${url}`);
  return response;
}

async function sha256(bytes) {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

function localAsset(path) {
  const base = new URL("./", import.meta.url);
  const url = new URL(path, base);
  if (url.origin !== base.origin || !url.pathname.startsWith(base.pathname)) {
    throw new Error("The site manifest contains an invalid asset path.");
  }
  return url;
}

async function initialize(id) {
  status(id, "Loading Python");
  const manifest = await (await checkedFetch(new URL("./web-manifest.json", import.meta.url))).json();
  const runtimeURL = manifest.pyodide?.index_url;
  if (manifest.schema_version !== 1 || manifest.pyodide.version !== PYODIDE_VERSION ||
      (runtimeURL !== PYODIDE_INDEX_URL && manifest.preview !== true) ||
      typeof runtimeURL !== "string" || !runtimeURL.endsWith("/") ||
      !/^[0-9a-f]{40}$/.test(manifest.source_commit) ||
      !manifest.wheel.path.startsWith(`assets/${manifest.source_commit}/`)) {
    throw new Error("The site manifest does not match this pinned runtime.");
  }
  const { loadPyodide } = await import(`${runtimeURL}pyodide.mjs`);
  const pyodide = await loadPyodide({ indexURL: runtimeURL });
  if (pyodide.version !== PYODIDE_VERSION) throw new Error("Unexpected Pyodide runtime version.");
  status(id, "Loading converter");
  await pyodide.loadPackage("micropip");
  const wheel = new Uint8Array(await (await checkedFetch(localAsset(manifest.wheel.path))).arrayBuffer());
  if (wheel.byteLength !== manifest.wheel.size || await sha256(wheel) !== manifest.wheel.sha256) {
    throw new Error("Converter wheel SHA-256 verification failed.");
  }
  const wheelName = manifest.wheel.path.split("/").at(-1);
  if (!/^py2fastrust-[A-Za-z0-9_.+-]+-py3-none-any\.whl$/.test(wheelName)) {
    throw new Error("The converter must be a pure Python wheel.");
  }
  const wheelPath = `/tmp/${wheelName}`;
  pyodide.FS.writeFile(wheelPath, wheel);
  pyodide.globals.set("_pytors_wheel", `emfs:${wheelPath}`);
  await pyodide.runPythonAsync("import micropip\nawait micropip.install(_pytors_wheel, deps=False)\ndel _pytors_wheel");
  pyodide.FS.unlink(wheelPath);
  const bridgeBytes = new Uint8Array(await (await checkedFetch(localAsset(manifest.bridge.path))).arrayBuffer());
  if (await sha256(bridgeBytes) !== manifest.bridge.sha256) {
    throw new Error("Converter bridge SHA-256 verification failed.");
  }
  pyodide.FS.writeFile("/home/pyodide/pytors_bridge.py", bridgeBytes);
  const bridge = pyodide.pyimport("pytors_bridge");
  const metadata = JSON.parse(bridge.initialize(JSON.stringify(manifest)));
  Object.assign(metadata, {
    source_commit: manifest.source_commit,
    preview: manifest.preview,
    pyodide_version: PYODIDE_VERSION,
    wheel_sha256: manifest.wheel.sha256,
  });
  return { bridge, metadata };
}

async function handle(message) {
  const { id, type } = message;
  try {
    if (type !== "init" && type !== "convert") throw new Error("Unknown worker request.");
    if (!runtimePromise) {
      runtimePromise = initialize(id).catch(error => {
        // A subsequent initialization request may retry a transient download.
        runtimePromise = undefined;
        throw error;
      });
    }
    const { bridge, metadata } = await runtimePromise;
    if (type === "init") {
      self.postMessage({ id, type: "ready", metadata });
      return;
    }
    status(id, "Converting");
    const result = JSON.parse(bridge.convert(JSON.stringify({ source: message.source, options: message.options })));
    self.postMessage({ id, type: "result", result });
  } catch (error) {
    self.postMessage({ id, type: "error", error: error instanceof Error ? error.message : String(error) });
  }
}

// Serialize requests so one initialized compiler bridge owns the virtual cwd.
self.addEventListener("message", event => {
  const message = event.data;
  if (!message || !["string", "number"].includes(typeof message.id)) return;
  queued = queued.then(() => handle(message));
});
