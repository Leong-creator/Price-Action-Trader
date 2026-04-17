#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASELINE_PATTERNS = (
    "test_data_pipeline.py",
    "test_strategy_signal_pipeline.py",
    "test_backtest_pipeline.py",
    "test_paper_execution_pipeline.py",
    "test_news_review_pipeline.py",
    "test_broker_contract_assessment.py",
)

OPTIONAL_SUITE_DIRS = {
    "golden": ROOT / "tests" / "golden_cases",
    "integration": ROOT / "tests" / "integration",
    "reliability": ROOT / "tests" / "reliability",
}

OPTIONAL_SUITE_DESCRIPTIONS = {
    "golden": "M8 golden-case catalog；无可执行测试时允许安全跳过",
    "integration": "M8C offline E2E 集成红线；无测试样本时允许安全跳过",
    "reliability": "M8B/M8C reliability 红线；无测试样本时允许安全跳过",
}

LOCAL_DATASET_SUFFIXES = (".csv", ".json")
REAL_HISTORY_DATASET_DIRS = (
    ROOT / "tests" / "reliability" / "real_history",
    ROOT / "tests" / "integration" / "real_history",
)


@dataclass(frozen=True)
class SuiteSpec:
    name: str
    kind: str
    location: Path
    pattern: str
    description: str


def build_suite_specs(selected_names: list[str] | None) -> list[SuiteSpec]:
    specs: list[SuiteSpec] = []

    if selected_names is None or "baseline" in selected_names:
        for pattern in BASELINE_PATTERNS:
            specs.append(
                SuiteSpec(
                    name=f"baseline:{pattern.removeprefix('test_').removesuffix('.py')}",
                    kind="baseline",
                    location=ROOT / "tests" / "unit",
                    pattern=pattern,
                    description="当前已存在的可靠性相关单元测试入口",
                )
            )

    for name, location in OPTIONAL_SUITE_DIRS.items():
        if selected_names is None or name in selected_names:
            specs.append(
                SuiteSpec(
                    name=name,
                    kind="optional",
                    location=location,
                    pattern="test_*.py",
                    description=OPTIONAL_SUITE_DESCRIPTIONS[name],
                )
            )

    return specs


def flatten_tests(suite: unittest.TestSuite) -> list[unittest.case.TestCase]:
    tests: list[unittest.case.TestCase] = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            tests.extend(flatten_tests(item))
        else:
            tests.append(item)
    return tests


def collect_test_files(spec: SuiteSpec) -> list[Path]:
    if not spec.location.exists():
        return []
    if spec.kind == "baseline":
        candidate = spec.location / spec.pattern
        return [candidate] if candidate.exists() else []
    return sorted(path for path in spec.location.rglob("test_*.py") if path.is_file())


def detect_local_dataset_fixtures() -> list[Path]:
    discovered: list[Path] = []
    for base in OPTIONAL_SUITE_DIRS.values():
        if not base.exists():
            continue
        for suffix in LOCAL_DATASET_SUFFIXES:
            discovered.extend(path for path in base.rglob(f"*{suffix}") if path.is_file())
    return sorted(discovered)


def detect_real_history_datasets() -> list[Path]:
    discovered: list[Path] = []
    for base in REAL_HISTORY_DATASET_DIRS:
        if not base.exists():
            continue
        for suffix in LOCAL_DATASET_SUFFIXES:
            discovered.extend(path for path in base.rglob(f"*{suffix}") if path.is_file())
    return sorted(discovered)


def load_module_from_path(path: Path) -> types.ModuleType:
    module_name = "codex_reliability_" + "_".join(path.relative_to(ROOT).with_suffix("").parts)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to create module spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def discover_suite(loader: unittest.TestLoader, spec: SuiteSpec) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    for path in collect_test_files(spec):
        if not fnmatch.fnmatch(path.name, spec.pattern):
            continue
        module = load_module_from_path(path)
        suite.addTests(loader.loadTestsFromModule(module))
    return suite


def list_suites(specs: list[SuiteSpec]) -> int:
    print("Available reliability suites:")
    print("  baseline    当前已存在的可靠性相关单元测试集合")
    for name, location in OPTIONAL_SUITE_DIRS.items():
        print(f"  {name:<11} {location.relative_to(ROOT)}")
        print(f"              {OPTIONAL_SUITE_DESCRIPTIONS[name]}")
    print()
    print("Current baseline test files:")
    for pattern in BASELINE_PATTERNS:
        print(f"  - tests/unit/{pattern}")
    return 0


def run_suites(specs: list[SuiteSpec], verbosity: int) -> int:
    loader = unittest.TestLoader()
    runner = unittest.TextTestRunner(verbosity=verbosity)

    executed = 0
    failed = False
    discovered_any = False

    print(f"[reliability] root={ROOT}")
    print("[reliability] boundary=paper/simulated")
    print("[reliability] network=disabled-by-design")
    print("[reliability] note=missing historical datasets are skipped, not fabricated")
    dataset_fixtures = detect_local_dataset_fixtures()
    if dataset_fixtures:
        print(f"[input] local_fixture_files=available count={len(dataset_fixtures)}")
    else:
        print("[input] local_fixture_files=deferred reason=no local CSV/JSON fixtures discovered")

    real_history_datasets = detect_real_history_datasets()
    if real_history_datasets:
        print(f"[input] real_historical_data=available count={len(real_history_datasets)}")
    else:
        print("[input] real_historical_data=deferred reason=no curated real-history datasets discovered")

    for spec in specs:
        suite = discover_suite(loader, spec)
        test_count = suite.countTestCases()
        print()
        print(f"[suite] {spec.name}")
        print(f"  location: {spec.location.relative_to(ROOT) if spec.location.exists() else spec.location}")
        print(f"  pattern: {spec.pattern}")
        print(f"  description: {spec.description}")

        if test_count == 0:
            print("  status: skipped")
            print("  reason: no discoverable tests yet; safe to continue within M8A skeleton")
            continue

        discovered_any = True
        executed += test_count
        result = runner.run(suite)
        if not result.wasSuccessful():
            failed = True
            print("  failure_hint: inspect the failing suite above; no synthetic result has been generated")

    print()
    if failed:
        print(f"[summary] failed after executing {executed} tests")
        return 1
    if not discovered_any:
        print("[summary] no tests discovered; verify suite selection or add skeleton tests first")
        return 0
    print(f"[summary] success; executed {executed} tests")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run local reliability-related test suites without external network access."
    )
    parser.add_argument(
        "--suite",
        action="append",
        choices=["baseline", "golden", "integration", "reliability"],
        help="Run only the selected suite. Can be passed multiple times.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available suite names and exit.",
    )
    parser.add_argument(
        "--verbosity",
        type=int,
        default=2,
        choices=[1, 2],
        help="unittest runner verbosity.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    specs = build_suite_specs(args.suite)

    if args.list:
        return list_suites(specs)

    if not specs:
        print("No suite selected. Use --list to inspect available suite names.", file=sys.stderr)
        return 2

    return run_suites(specs, verbosity=args.verbosity)


if __name__ == "__main__":
    raise SystemExit(main())
