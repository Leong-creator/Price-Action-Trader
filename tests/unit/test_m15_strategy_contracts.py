import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.m15_strategy_contracts_lib import (
    CONTRACT_STAGE_ZH,
    DEFAULT_CONTRACTS_DIR,
    StrategyContractError,
    get_contract_for_runtime,
    load_contract,
    load_contracts,
    persist_runtime_state,
    stable_contract_hash,
    validate_contract,
    write_state_atomic,
)
from scripts.m15_longbridge_realtime_signal_router_lib import PRICE_ACTION_RUNTIME_SPECS


EXPECTED_RUNTIME_IDS = {
    "M10-PA-001-1d",
    "M10-PA-002-5m",
    "M10-PA-004-long-1d",
    "M10-PA-004-MBF-QC-1d",
    "M10-PA-007-1d",
    "M10-PA-008-1d",
    "M10-PA-012-5m",
    "M12-FTD-001-pullback-guard-confirm-1d",
    "M10-PA-002-5m-short",
    "M10-PA-013-5m-short",
    "M10-PA-011-ORB-R1-5m-short",
}


class M15StrategyContractsTest(unittest.TestCase):
    def test_stage_chinese_mapping_is_complete(self):
        self.assertEqual(
            CONTRACT_STAGE_ZH,
            {
                "contract-draft-v1": "规则草案",
                "shadow-v1": "实时影子",
                "paper-v1": "模拟交易",
                "full-v1": "完整执行版",
            },
        )

    def test_loads_exactly_the_final_eleven_runtime_contracts(self):
        contracts = load_contracts()
        self.assertEqual(set(contracts), EXPECTED_RUNTIME_IDS)
        self.assertEqual(len(contracts), 11)
        for contract in contracts.values():
            self.assertRegex(contract["contract_hash"], r"^[0-9a-f]{64}$")
            self.assertEqual(contract["stage_zh"], CONTRACT_STAGE_ZH[contract["stage"]])
            self.assertFalse(contract["execution_boundaries"]["local_simulation_as_signal_source"])
            self.assertFalse(contract["data_requirements"]["local_simulation_ledger"])

    def test_visual_strategies_remain_explicit_contract_drafts(self):
        contracts = load_contracts()
        for runtime_id in ("M10-PA-004-long-1d", "M10-PA-007-1d", "M10-PA-008-1d"):
            contract = contracts[runtime_id]
            self.assertEqual(contract["stage"], "contract-draft-v1")
            self.assertTrue(contract["visual_acceptance"]["required"])
            self.assertEqual(contract["visual_acceptance"]["status"], "pending")
            self.assertTrue(contract["visual_acceptance"]["checks_zh"])

    def test_stable_hash_ignores_key_order_and_derived_fields(self):
        path = DEFAULT_CONTRACTS_DIR / "M10-PA-002-5m.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        reordered = dict(reversed(list(raw.items())))
        enriched = load_contract(path)
        self.assertEqual(stable_contract_hash(raw), stable_contract_hash(reordered))
        self.assertEqual(stable_contract_hash(raw), stable_contract_hash(enriched))

    def test_validation_rejects_missing_field_and_unsafe_boundary(self):
        contract = load_contracts()["M10-PA-001-1d"]
        missing = copy.deepcopy(contract)
        del missing["entry_rules"]
        with self.assertRaisesRegex(StrategyContractError, "missing required contract fields: entry_rules"):
            validate_contract(missing)

        unsafe = copy.deepcopy(contract)
        unsafe["execution_boundaries"]["live_execution"] = True
        with self.assertRaisesRegex(StrategyContractError, "live_execution must be false"):
            validate_contract(unsafe)

    def test_draft_requires_visual_acceptance(self):
        contract = load_contracts()["M10-PA-007-1d"]
        contract["visual_acceptance"]["required"] = False
        with self.assertRaisesRegex(StrategyContractError, "requires explicit visual acceptance"):
            validate_contract(contract)

    def test_loader_rejects_duplicate_runtime(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            directory = Path(temporary_dir)
            source = DEFAULT_CONTRACTS_DIR / "M10-PA-001-1d.json"
            payload = source.read_text(encoding="utf-8")
            (directory / "a.json").write_text(payload, encoding="utf-8")
            (directory / "b.json").write_text(payload, encoding="utf-8")
            with self.assertRaisesRegex(StrategyContractError, "duplicate runtime_id"):
                load_contracts(directory)

    def test_get_contract_for_runtime(self):
        contract = get_contract_for_runtime("M10-PA-012-5m")
        self.assertEqual(contract["setup"]["rule"], "pa012_5m_contract_v1")
        with self.assertRaisesRegex(StrategyContractError, "not found"):
            get_contract_for_runtime("M10-PA-999-1d")

    def test_executable_contract_rule_names_match_runtime_specs(self):
        contracts = load_contracts()
        for runtime_id, contract in contracts.items():
            if contract["stage"] not in {"paper-v1", "full-v1"}:
                continue
            if runtime_id not in PRICE_ACTION_RUNTIME_SPECS:
                continue
            self.assertEqual(
                contract["setup"]["rule"],
                PRICE_ACTION_RUNTIME_SPECS[runtime_id]["rule"],
                runtime_id,
            )

    def test_atomic_state_write_replaces_content_and_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            state_path = Path(temporary_dir) / "nested" / "state.json"
            write_state_atomic(state_path, {"status": "draft", "revision": 1})
            write_state_atomic(state_path, {"status": "accepted", "revision": 2})
            self.assertEqual(
                json.loads(state_path.read_text(encoding="utf-8")),
                {"status": "accepted", "revision": 2},
            )
            self.assertEqual(list(state_path.parent.glob(".*.tmp")), [])

    def test_persist_runtime_state_uses_runtime_scoped_file(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = persist_runtime_state("M10-PA-002-5m", {"status": "paper-v1"}, temporary_dir)
            self.assertEqual(path.name, "M10-PA-002-5m.json")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["status"], "paper-v1")
            with self.assertRaisesRegex(StrategyContractError, "invalid runtime_id"):
                persist_runtime_state("../escape", {}, temporary_dir)


if __name__ == "__main__":
    unittest.main()
