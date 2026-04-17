from __future__ import annotations

import tempfile
from functools import lru_cache
from pathlib import Path

from scripts.kb_atomization_lib import (
    DEFAULT_ATOM_OUTPUT,
    DEFAULT_CALLABLE_OUTPUT,
    DEFAULT_CHUNK_OUTPUT,
    DEFAULT_SOURCE_OUTPUT,
    build_callable_index,
    build_chunk_manifest,
    build_knowledge_atoms,
    build_source_manifest,
    load_json,
    load_jsonl,
    query_atoms,
    validate_knowledge_atoms,
    validate_source_manifest,
    write_json,
    write_jsonl,
)


@lru_cache(maxsize=1)
def build_atomization_fixture() -> dict[str, object]:
    if (
        DEFAULT_SOURCE_OUTPUT.exists()
        and DEFAULT_CHUNK_OUTPUT.exists()
        and DEFAULT_ATOM_OUTPUT.exists()
        and DEFAULT_CALLABLE_OUTPUT.exists()
    ):
        source_manifest = load_json(DEFAULT_SOURCE_OUTPUT)
        chunks = load_jsonl(DEFAULT_CHUNK_OUTPUT)
        atoms = load_jsonl(DEFAULT_ATOM_OUTPUT)
        callable_index = load_json(DEFAULT_CALLABLE_OUTPUT)
        return {
            "temp_dir": DEFAULT_SOURCE_OUTPUT.parent,
            "source_manifest_path": DEFAULT_SOURCE_OUTPUT,
            "chunk_manifest_path": DEFAULT_CHUNK_OUTPUT,
            "atom_path": DEFAULT_ATOM_OUTPUT,
            "callable_path": DEFAULT_CALLABLE_OUTPUT,
            "source_manifest": source_manifest,
            "chunks": chunks,
            "atoms": atoms,
            "callable_index": callable_index,
        }

    temp_dir = Path(tempfile.mkdtemp(prefix="pat-m8b2a-"))
    source_path = temp_dir / "source_manifest.json"
    chunk_path = temp_dir / "chunk_manifest.jsonl"
    atom_path = temp_dir / "knowledge_atoms.jsonl"
    callable_path = temp_dir / "knowledge_callable_index.json"

    source_manifest = build_source_manifest()
    write_json(source_path, source_manifest)
    chunks = build_chunk_manifest(source_manifest)
    write_jsonl(chunk_path, chunks)
    atoms = build_knowledge_atoms(source_manifest, chunks)
    write_jsonl(atom_path, atoms)
    callable_index = build_callable_index(source_manifest, chunks, atoms)
    write_json(callable_path, callable_index)

    return {
        "temp_dir": temp_dir,
        "source_manifest_path": source_path,
        "chunk_manifest_path": chunk_path,
        "atom_path": atom_path,
        "callable_path": callable_path,
        "source_manifest": source_manifest,
        "chunks": chunks,
        "atoms": atoms,
        "callable_index": callable_index,
    }


def load_fixture() -> dict[str, object]:
    fixture = build_atomization_fixture()
    return {
        **fixture,
        "source_manifest": load_json(fixture["source_manifest_path"]),
        "chunks": load_jsonl(fixture["chunk_manifest_path"]),
        "atoms": load_jsonl(fixture["atom_path"]),
        "callable_index": load_json(fixture["callable_path"]),
    }


def validation_errors() -> tuple[list[str], list[str]]:
    fixture = load_fixture()
    source_errors = validate_source_manifest(fixture["source_manifest"])
    atom_errors = validate_knowledge_atoms(
        fixture["source_manifest"],
        fixture["chunks"],
        fixture["atoms"],
    )
    return source_errors, atom_errors


def query_fixture(**filters: str) -> list[dict[str, object]]:
    fixture = load_fixture()
    return query_atoms(
        atoms=fixture["atoms"],
        callable_index=fixture["callable_index"],
        **filters,
    )
