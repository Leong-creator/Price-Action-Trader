from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_module(module_name: str, relative_path: str):
    module_path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


MODULE = load_module(
    "validate_strategy_factory_contract",
    "scripts/validate_strategy_factory_contract.py",
)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_doc(path: Path, config_path: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            f"<!-- strategy_factory_provider_contract={{"
            f"\"active_provider_config_path\":\"{config_path}\","
            f"\"primary_provider_runtime_source\":\"source_order[0]\""
            f"}} -->\n"
        ),
        encoding="utf-8",
    )


class TestStrategyFactoryContract(unittest.TestCase):
    def test_validate_provider_contract_passes_when_docs_config_and_run_state_align(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "config" / "strategy_factory" / "active_provider_config.json"
            run_state_path = root / "reports" / "strategy_lab" / "strategy_factory" / "run_state.json"
            write_json(config_path, {"source_order": ["longbridge"]})
            write_json(
                run_state_path,
                {
                    "active_provider_config_path": config_path.as_posix(),
                    "primary_provider": "longbridge",
                },
            )
            docs = [
                root / "plans" / "active-plan.md",
                root / "docs" / "status.md",
                root / "docs" / "acceptance.md",
            ]
            for doc in docs:
                write_doc(doc, config_path.as_posix())

            errors = MODULE.validate_provider_contract(
                doc_paths=docs,
                run_state_path=run_state_path,
            )
            self.assertEqual(errors, [])

    def test_validate_provider_contract_fails_on_run_state_provider_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "config" / "strategy_factory" / "active_provider_config.json"
            run_state_path = root / "reports" / "strategy_lab" / "strategy_factory" / "run_state.json"
            write_json(config_path, {"source_order": ["longbridge"]})
            write_json(
                run_state_path,
                {
                    "active_provider_config_path": config_path.as_posix(),
                    "primary_provider": "yfinance",
                },
            )
            docs = [
                root / "plans" / "active-plan.md",
                root / "docs" / "status.md",
                root / "docs" / "acceptance.md",
            ]
            for doc in docs:
                write_doc(doc, config_path.as_posix())

            errors = MODULE.validate_provider_contract(
                doc_paths=docs,
                run_state_path=run_state_path,
            )
            self.assertEqual(
                errors,
                [f"{run_state_path}: primary_provider must equal 'longbridge'"],
            )


if __name__ == "__main__":
    unittest.main()
