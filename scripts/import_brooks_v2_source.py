#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = Path("/home/hgl/projects/Al Brooks extra/knowledge_base_v2")
DEFAULT_DEST = (
    PROJECT_ROOT
    / "knowledge"
    / "raw"
    / "brooks"
    / "transcribed_v2"
    / "al_brooks_price_action_course_v2"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def copy_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def sync_tree(src: Path, dest: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(src)
    dest.mkdir(parents=True, exist_ok=True)
    for path in sorted(src.rglob("*")):
        relative = path.relative_to(src)
        target = dest / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        copy_file(path, target)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_checksum_file(root: Path, paths: list[Path], output: Path) -> dict[str, object]:
    lines: list[str] = []
    total_bytes = 0
    for path in sorted(paths):
        if not path.is_file():
            continue
        total_bytes += path.stat().st_size
        relative = path.relative_to(root).as_posix()
        lines.append(f"{sha256_file(path)}  {relative}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return {"file_count": len(lines), "total_bytes": total_bytes, "checksum_path": output.name}


def collect_files(root: Path, relative_roots: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for relative_root in relative_roots:
        target = root / relative_root
        if not target.exists():
            continue
        if target.is_file():
            files.append(target)
            continue
        files.extend(path for path in target.rglob("*") if path.is_file())
    return sorted(files)


def build_manifest(dest: Path, source: Path, include_assets: bool) -> dict[str, object]:
    units = sorted((dest / "units").glob("*.md"))
    evidence = sorted((dest / "evidence").glob("*.md"))
    asset_root = dest / "assets" / "evidence"
    asset_files = sorted(path for path in asset_root.rglob("*") if path.is_file()) if asset_root.exists() else []
    return {
        "schema_version": "m10.brooks-v2-import.v1",
        "generated_at": utc_now(),
        "external_source_root": str(source),
        "raw_root": dest.relative_to(PROJECT_ROOT).as_posix(),
        "included": {
            "readme": (dest / "README.md").exists(),
            "units": len(units),
            "evidence_pages": len(evidence),
            "assets_evidence_copied": include_assets and asset_root.exists(),
            "assets_evidence_files": len(asset_files),
            "assets_evidence_bytes": sum(path.stat().st_size for path in asset_files),
        },
        "git_tracking_policy": {
            "text_units_and_evidence": "tracked",
            "assets_evidence": "local_only_ignored_by_git",
            "asset_checksums": "tracked",
        },
        "source_priority_role": "highest_priority_strategy_source_for_m10",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Brooks v2 manual transcript into knowledge/raw.")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--dest", default=str(DEFAULT_DEST))
    parser.add_argument("--skip-assets", action="store_true")
    args = parser.parse_args()

    source = Path(args.source)
    dest = Path(args.dest)
    if not source.exists():
        raise FileNotFoundError(source)

    copy_file(source / "README.md", dest / "README.md")
    sync_tree(source / "units", dest / "units")
    sync_tree(source / "evidence", dest / "evidence")
    include_assets = not args.skip_assets
    if include_assets:
        sync_tree(source / "assets" / "evidence", dest / "assets" / "evidence")

    tracked_files = collect_files(dest, ("README.md", "units", "evidence"))
    tracked_summary = write_checksum_file(dest, tracked_files, dest / "checksums.sha256")

    asset_summary = {"file_count": 0, "total_bytes": 0, "checksum_path": "assets_evidence_checksums.sha256"}
    if include_assets:
        asset_files = collect_files(dest, ("assets/evidence",))
        asset_summary = write_checksum_file(dest, asset_files, dest / "assets_evidence_checksums.sha256")

    manifest = build_manifest(dest, source, include_assets)
    manifest["tracked_text_checksums"] = tracked_summary
    manifest["asset_checksums"] = asset_summary
    manifest_path = dest / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        "Imported Brooks v2: "
        f"units={manifest['included']['units']} "
        f"evidence={manifest['included']['evidence_pages']} "
        f"asset_files={manifest['included']['assets_evidence_files']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
