#!/usr/bin/env python3
"""Check built Pages assets and initialize their actual wheel without converting."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def asset(site, name):
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Invalid site asset path: " + name)
    result = (site / relative).resolve()
    if not result.is_relative_to(site):
        raise ValueError("Site asset escapes the build directory: " + name)
    return result


def verify_site(site):
    manifest = json.loads((site / "web-manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["site_files"].items():
        if digest(asset(site, name).read_bytes()) != expected:
            raise ValueError("Site asset SHA-256 mismatch: " + name)
    wheel_path = asset(site, manifest["wheel"]["path"])
    data = wheel_path.read_bytes()
    if len(data) != manifest["wheel"]["size"] or digest(data) != manifest["wheel"]["sha256"]:
        raise ValueError("Wheel size or SHA-256 mismatch.")
    bridge = asset(site, manifest["bridge"]["path"])
    if digest(bridge.read_bytes()) != manifest["bridge"]["sha256"]:
        raise ValueError("Bridge SHA-256 mismatch.")
    expected = {name: value for name, value in manifest["source_files"].items()
                if name.startswith("py2fastrust/")}
    with zipfile.ZipFile(wheel_path) as wheel:
        names = [name for name in wheel.namelist()
                 if name.startswith("py2fastrust/") and not name.endswith("/")]
        if not expected or len(names) != len(set(names)) or set(names) != set(expected):
            raise ValueError("Wheel package inventory differs from the manifest.")
        for name in names:
            contents = wheel.read(name)
            if digest(contents) != expected[name]:
                raise ValueError("Wheel package SHA-256 mismatch: " + name)
            if name.endswith(".py"):
                compile(contents, name, "exec")
    return manifest, wheel_path, bridge


def initialize_wheel(site):
    """Run only in a fresh isolated child so source imports cannot hide errors."""
    manifest, wheel, bridge_path = verify_site(site)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(wheel))
    import py2fastrust
    if not Path(py2fastrust.__file__).is_relative_to(wheel):
        raise RuntimeError("Initialization did not import the built wheel.")
    spec = importlib.util.spec_from_file_location("pytors_built_bridge", bridge_path)
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    if not callable(bridge.convert):
        raise RuntimeError("The browser conversion entry point is missing.")
    # /work is supplied by Pyodide. Host checks use the same bridge with a
    # disposable working directory, without altering the published bridge.
    with tempfile.TemporaryDirectory(prefix="pytors-wheel-init-") as directory:
        bridge.WORK_DIRECTORY = Path(directory) / "work"
        try:
            metadata = json.loads(bridge.initialize(json.dumps(manifest)))
            checks = metadata.get("smoke_checks")
            required = {"ast", "symtable", "compile", "sha256", "resources"}
            if (not isinstance(checks, dict) or not required.issubset(checks)
                    or any(value is not True for value in checks.values())):
                raise RuntimeError("Built-wheel initialization checks did not pass.")
        finally:
            os.chdir(site)
    return {"source_commit": manifest["source_commit"],
            "wheel_sha256": manifest["wheel"]["sha256"],
            "package_origin": py2fastrust.__file__,
            "resource_count": metadata["resource_count"],
            "smoke_checks": metadata["smoke_checks"],
            "conversions_run": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--initialize-wheel", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    site = args.site.resolve()
    if args.initialize_wheel:
        print(json.dumps(initialize_wheel(site)))
        return
    # -I excludes repository/PYTHONPATH imports; -B leaves the artifact intact.
    result = subprocess.run([
        sys.executable, "-I", "-B", str(Path(__file__).resolve()),
        "--site", str(site), "--initialize-wheel",
    ], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Built Pages package initialization failed:\n" + result.stderr)
    print(json.dumps(json.loads(result.stdout)))


if __name__ == "__main__":
    main()
