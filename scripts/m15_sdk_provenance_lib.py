"""Offline SDK provenance: a reviewed official wheel is the trust anchor.

The expected wheel digest must be obtained independently (for example from the
official PyPI release metadata), reviewed and committed in config. This module
never learns a trusted digest from the installed package or contacts a broker.
"""
from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any
from urllib.parse import urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TRUST_PATH = Path("config/m15_official_sdk_artifact.json")
RECEIPT_PATH = Path("reports/runtime/m15_sdk_environment.json")
ENVIRONMENT_PATH = Path(".venv-m15")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("sdk_provenance_invalid_object")
    return value


def trusted_artifact(root: Path = ROOT) -> dict[str, Any]:
    anchor = _read_object(root / TRUST_PATH)
    url = urlsplit(str(anchor.get("source_url", "")))
    filename = str(anchor.get("filename", ""))
    if (anchor.get("schema_version") != "m15.official-sdk-artifact.v1"
            or anchor.get("version") != "4.5.0"
            or not re.fullmatch(r"[0-9a-f]{64}", str(anchor.get("sha256", "")))
            or not filename.startswith("longbridge-4.5.0-") or not filename.endswith(".whl")
            or Path(filename).name != filename
            or url.scheme != "https" or url.netloc != "files.pythonhosted.org"
            or PurePosixPath(url.path).name != filename or url.query or url.fragment):
        raise ValueError("sdk_trusted_artifact_invalid")
    return anchor


def inspect_environment(wheel: Path, root: Path = ROOT) -> dict[str, Any]:
    """Compare installed files with independently pinned wheel; no SDK import."""
    root = root.resolve()
    anchor = trusted_artifact(root)
    wheel = wheel.resolve()
    if wheel.name != anchor["filename"] or digest(wheel) != anchor["sha256"]:
        raise ValueError("sdk_wheel_hash_mismatch")
    if (Path(sys.prefix).resolve() != (root / ENVIRONMENT_PATH).resolve()
            or Path(sys.executable).absolute() != root / ENVIRONMENT_PATH / "bin/python"):
        raise ValueError("sdk_interpreter_not_canonical")
    if os.environ.get("LD_PRELOAD") or os.environ.get("M15_LONGBRIDGE_DNS_OVERRIDES"):
        raise ValueError("sdk_legacy_process_injection")
    if list(Path(sys.prefix).glob(".m15-longbridge-sdk*.json")):
        raise ValueError("sdk_local_patch_marker_present")
    dist = importlib.metadata.distribution("longbridge")
    if dist.version != anchor["version"]:
        raise ValueError("sdk_version_mismatch")
    package = Path(dist.locate_file("longbridge")).resolve()
    if not package.is_relative_to((root / ENVIRONMENT_PATH).resolve()):
        raise ValueError("sdk_package_outside_canonical_environment")
    spec = importlib.machinery.PathFinder.find_spec("longbridge")
    locations = list(spec.submodule_search_locations or []) if spec else []
    if len(locations) != 1 or Path(locations[0]).resolve() != package:
        raise ValueError("sdk_import_shadowed")
    module = importlib.machinery.PathFinder.find_spec("longbridge.openapi", locations)
    if module is None or not module.origin:
        raise ValueError("sdk_native_module_missing")
    module_path = Path(module.origin).resolve()
    for name in ("longbridge", "longbridge.openapi"):
        loaded = sys.modules.get(name)
        if loaded is not None:
            expected = Path(spec.origin).resolve() if name == "longbridge" else module_path
            if Path(getattr(loaded, "__file__", "")).resolve() != expected:
                raise ValueError("sdk_loaded_module_shadowed")
    files: dict[str, str] = {}
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("sdk_wheel_duplicate_members")
        for name in names:
            member = PurePosixPath(name)
            if member.is_absolute() or ".." in member.parts:
                raise ValueError("sdk_wheel_invalid_member")
            if name.endswith("/"):
                continue
            if not (name.startswith("longbridge/") or name.endswith(".dist-info/METADATA")):
                continue
            installed = Path(dist.locate_file(name)).resolve()
            if not installed.is_relative_to((root / ENVIRONMENT_PATH).resolve()):
                raise ValueError("sdk_installed_file_outside_environment")
            expected_hash = hashlib.sha256(archive.read(name)).hexdigest()
            if not installed.is_file() or digest(installed) != expected_hash:
                raise ValueError("sdk_installed_file_mismatch:" + name)
            files[name] = expected_hash
    package_files = {"longbridge/" + p.relative_to(package).as_posix()
                     for p in package.rglob("*") if p.is_file()
                     and "__pycache__" not in p.parts and p.suffix != ".pyc"}
    if package_files != {name for name in files if name.startswith("longbridge/")}:
        raise ValueError("sdk_unexpected_package_files")
    if not module_path.is_relative_to(package) or "longbridge/" + module_path.relative_to(package).as_posix() not in files:
        raise ValueError("sdk_native_module_not_in_wheel")
    return {
        "schema_version": "m15.sdk-environment.v1",
        "trust_record_sha256": digest(root / TRUST_PATH),
        "version": dist.version,
        "wheel_path": str(wheel), "wheel_sha256": anchor["sha256"],
        "interpreter_path": str(Path(sys.executable).absolute()),
        "interpreter_realpath": str(Path(sys.executable).resolve()),
        "interpreter_sha256": digest(Path(sys.executable)),
        "environment_path": str(Path(sys.prefix).resolve()),
        "module_path": str(module_path), "module_sha256": digest(module_path),
        "installed_files": files,
    }


def issue_environment_receipt(wheel: Path, root: Path = ROOT) -> dict[str, Any]:
    receipt = inspect_environment(wheel, root)
    destination = root / RECEIPT_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return receipt


def verify_environment(root: Path = ROOT) -> dict[str, Any]:
    try:
        receipt = _read_object(root / RECEIPT_PATH)
        actual = inspect_environment(Path(receipt["wheel_path"]), root)
        if actual != receipt:
            raise ValueError("sdk_environment_receipt_drift")
        return {"verified": True, "issues": [], "environment": actual}
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile,
            importlib.metadata.PackageNotFoundError) as exc:
        return {"verified": False, "issues": ["sdk_provenance_failed:" + str(exc)], "environment": {}}
