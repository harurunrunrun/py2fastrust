#!/usr/bin/env python3
"""Build an isolated Pages site and its verified, commit-addressed Python wheel."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile


PYODIDE_VERSION = "314.0.7"
PYODIDE_INDEX_URL = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"
SITE_FILES = ("index.html", "style.css", "app.js", "worker.mjs", "bridge.py")
RESOURCE_DIRECTORIES = {"runtime", "stdlib", "grammar", "licenses", "unicode", "vendor"}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def git(repository, *args):
    return subprocess.check_output(["git", "-C", str(repository), *args], text=True).strip()


def package_files(source):
    """All source package files must survive wheel construction byte for byte."""
    package = source / "py2fastrust"
    result = {}
    for directory, subdirectories, filenames in os.walk(package):
        subdirectories[:] = sorted(name for name in subdirectories
                                    if name != "__pycache__" and not name.startswith(".env"))
        for name in sorted(filenames):
            if name.endswith((".pyc", ".pyo")) or name.startswith(".env"):
                continue
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError(f"Package inputs must not be symlinks: {path}")
            result[path.relative_to(package).as_posix()] = path.read_bytes()
    if not result:
        raise ValueError("No py2fastrust package files were found.")
    return result


def verify_wheel(wheel_path, expected):
    """Reject missing resources, stale package files, and platform wheels."""
    with zipfile.ZipFile(wheel_path) as wheel:
        wheel_metadata = [name for name in wheel.namelist() if name.endswith(".dist-info/WHEEL")]
        if len(wheel_metadata) != 1:
            raise ValueError("Expected exactly one wheel metadata file.")
        metadata = wheel.read(wheel_metadata[0]).decode("utf-8")
        if "Root-Is-Purelib: true\n" not in metadata or "Tag: py3-none-any\n" not in metadata:
            raise ValueError("The browser converter requires a pure Python py3-none-any wheel.")
        actual = {name.removeprefix("py2fastrust/"): wheel.read(name)
                  for name in wheel.namelist()
                  if name.startswith("py2fastrust/") and not name.endswith("/")}
        if actual.keys() != expected.keys():
            missing = sorted(expected.keys() - actual.keys())
            extra = sorted(actual.keys() - expected.keys())
            raise ValueError(f"Wheel package inventory differs; missing={missing}, extra={extra}")
        for name, data in expected.items():
            if actual[name] != data:
                raise ValueError("Wheel package file differs from source: " + name)
    return [
        {"path": name, "sha256": sha256(data), "size": len(data)}
        for name, data in sorted(expected.items())
        if name.split("/", 1)[0] in RESOURCE_DIRECTORIES
    ]


def export_commit(repository, revision, destination):
    commit = git(repository, "rev-parse", "--verify", revision + "^{commit}")
    timestamp = git(repository, "show", "-s", "--format=%ct", commit)
    archive_path = destination.parent / "source.tar"
    subprocess.run(["git", "-C", str(repository), "archive", "--format=tar",
                    "--output", str(archive_path), commit], check=True)
    with tarfile.open(archive_path) as archive:
        archive.extractall(destination, filter="data")
    return commit, timestamp


def build_site(source, output, commit, *, preview=False, epoch="315532800", runtime_url=PYODIDE_INDEX_URL):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("A full 40-character source commit is required.")
    if not preview and runtime_url != PYODIDE_INDEX_URL:
        raise ValueError("A runtime mirror is allowed only for an explicit preview build.")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory must be empty: " + str(output))
    for name in SITE_FILES:
        if not (source / "web" / name).is_file():
            raise ValueError("The source snapshot is missing web/" + name)
    config = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))
    if config.get("build-system", {}).get("build-backend") != "setuptools.build_meta":
        raise ValueError("The Pages builder requires the package's setuptools.build_meta backend.")
    package = config["project"]
    if package.get("dependencies"):
        raise ValueError("Browser packaging must explicitly account for package dependencies.")
    expected = package_files(source)
    with tempfile.TemporaryDirectory(prefix="pytors-wheel-") as temporary:
        build_root = Path(temporary)
        # Setuptools writes egg-info/build files, so it receives a disposable copy.
        wheel_source = build_root / "source"
        wheel_source.mkdir()
        shutil.copy2(source / "pyproject.toml", wheel_source / "pyproject.toml")
        shutil.copy2(source / "README.md", wheel_source / "README.md")
        if (source / "LICENSE").exists():
            shutil.copy2(source / "LICENSE", wheel_source / "LICENSE")
        for name, data in expected.items():
            path = wheel_source / "py2fastrust" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        environment = os.environ.copy()
        environment["SOURCE_DATE_EPOCH"] = epoch
        # Invoke the package's PEP 517 backend in a child process. The repository
        # needs setuptools>=77, but no extra build frontend or network access.
        subprocess.run([
            sys.executable, "-c",
            "import sys; import setuptools.build_meta as backend; "
            "backend.build_wheel(sys.argv[1])",
            str(build_root / "wheel"),
        ], cwd=wheel_source, env=environment, check=True)
        wheels = list((build_root / "wheel").glob("*.whl"))
        if len(wheels) != 1:
            raise ValueError("Expected exactly one built wheel.")
        wheel = wheels[0]
        resources = verify_wheel(wheel, expected)
        if not resources:
            raise ValueError("The wheel has no runtime resource inventory.")
        wheel_bytes = wheel.read_bytes()
        wheel_relative = Path("assets") / commit / wheel.name
        output.mkdir(parents=True, exist_ok=True)
        (output / wheel_relative).parent.mkdir(parents=True)
        (output / wheel_relative).write_bytes(wheel_bytes)
    for name in SITE_FILES:
        shutil.copy2(source / "web" / name, output / name)
    (output / ".nojekyll").touch()
    manifest = {
        "schema_version": 1,
        "source_commit": commit,
        "preview": preview,
        "package": {"name": package["name"], "version": package["version"]},
        "pyodide": {"version": PYODIDE_VERSION, "index_url": runtime_url},
        "wheel": {"path": wheel_relative.as_posix(), "sha256": sha256(wheel_bytes),
                  "size": len(wheel_bytes)},
        "bridge": {"path": "bridge.py", "sha256": sha256((output / "bridge.py").read_bytes())},
        "resources": resources,
        "source_files": {
            **{"py2fastrust/" + name: sha256(data) for name, data in sorted(expected.items())},
            **{name: sha256((source / name).read_bytes())
               for name in ("pyproject.toml", "README.md", "LICENSE") if (source / name).is_file()},
            **{"web/" + name: sha256((source / "web" / name).read_bytes()) for name in SITE_FILES},
        },
        "site_files": {name: sha256((output / name).read_bytes()) for name in SITE_FILES},
    }
    (output / "web-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("dist/web"))
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--ref", default="HEAD", help="Committed snapshot to export (default: HEAD)")
    parser.add_argument("--preview-source", type=Path,
                        help="Use uncommitted files for local verification; marks the manifest preview:true")
    parser.add_argument("--source-commit", help="Full reference commit for --preview-source")
    parser.add_argument("--pyodide-index-url", default=PYODIDE_INDEX_URL,
                        help="Pinned runtime mirror for preview tests only")
    args = parser.parse_args(argv)
    if sys.version_info[:2] != (3, 14):
        parser.error("Run this builder with Python 3.14.")
    if bool(args.preview_source) != bool(args.source_commit):
        parser.error("--preview-source and --source-commit must be supplied together.")
    if not args.pyodide_index_url.endswith("/"):
        parser.error("--pyodide-index-url must end with /.")
    with tempfile.TemporaryDirectory(prefix="pytors-site-source-") as temporary:
        if args.preview_source:
            source = args.preview_source.resolve()
            commit, epoch = args.source_commit, "315532800"
        else:
            source = Path(temporary) / "source"
            commit, epoch = export_commit(args.repository.resolve(), args.ref, source)
        manifest = build_site(source, args.output.resolve(), commit,
                              preview=bool(args.preview_source), epoch=epoch,
                              runtime_url=args.pyodide_index_url)
    print(json.dumps({"output": str(args.output.resolve()), "source_commit": manifest["source_commit"],
                      "preview": manifest["preview"], "wheel_sha256": manifest["wheel"]["sha256"],
                      "wheel_bytes": manifest["wheel"]["size"], "resources": len(manifest["resources"])}))


if __name__ == "__main__":
    main()
