#!/usr/bin/env python3
"""Smoke checks for the multi-property repair loop.

The script keeps the checks intentionally small:

- Python compilation for the repair modules;
- a formula-relation pruning assertion;
- one DB no-hint symbolic repair run;
- one dataset default no-hint run;
- optionally, the no-hint/hint comparison with symbolic repair and admissibility enabled.
"""

from __future__ import annotations

import argparse
import json
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VERIFYTA = Path(r"D:\tool\programming\uppaal\UPPAAL-5.0.0\bin\verifyta.exe")


def run(command: list[str], timeout: int = 180) -> None:
    print("$ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True, timeout=timeout)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def compile_modules() -> None:
    modules = [
        ROOT / "src/repair/property_relations.py",
        ROOT / "src/repair/tdt_smt.py",
        ROOT / "src/repair/multi_property_repair.py",
        ROOT / "src/repair/liveness_checks.py",
        ROOT / "src/admissibility/tartar_admissibility.py",
        ROOT / "src/utils/verify_automata.py",
    ]
    for module in modules:
        py_compile.compile(str(module), doraise=True)


def check_relation_pruning() -> None:
    sys.path.insert(0, str(ROOT))
    from src.repair.multi_property_repair import relation_pruned_symbolic_indices
    from src.repair.property_relations import analyze_property_relations

    formulas = ["A[] x <= 3", "A[] x <= 5", "A[] x <= 3"]
    relations = analyze_property_relations(formulas, {"x"}, {})
    selected, notes = relation_pruned_symbolic_indices({1, 2, 3}, relations)
    if selected != [1]:
        raise AssertionError(f"expected only strongest representative P1, got {selected}; notes={notes}")


def check_db_no_hint_symbolic(verifyta: Path, output_root: Path) -> None:
    output_dir = output_root / "db_no_hint_symbolic"
    shutil.rmtree(output_dir, ignore_errors=True)
    run(
        [
            sys.executable,
            "scripts/repair_multi_property.py",
            "repair",
            "--model",
            "models/bound_modified_error_dataset/TarTarRepairedDB/1repaireddb2/bound_mod_0003/model.xml",
            "--properties",
            "models/bound_modified_error_dataset/TarTarRepairedDB/1repaireddb2/bound_mod_0003/properties.q",
            "--output-dir",
            str(output_dir),
            "--verifyta",
            str(verifyta),
            "--max-candidates",
            "30",
            "--max-changes",
            "4",
            "--max-refinement-rounds",
            "3",
            "--symbolic-use-dbm",
            "--timeout",
            "60",
        ],
        timeout=180,
    )
    report = load_json(output_dir / "repair_report.json")
    if report["status"] != "repaired" or report["final_status"] != "satisfied":
        raise AssertionError(f"DB symbolic repair failed: {report['status']} / {report['final_status']}")
    if report["initial_status"] != "not_satisfied":
        raise AssertionError(f"no-hint run should verify initial status, got {report['initial_status']}")
    if "trace_site_coverage_rounds" not in report.get("analysis", {}):
        raise AssertionError("expected trace-site coverage analysis in symbolic report")


def check_dataset_default_no_hint(verifyta: Path, output_root: Path) -> None:
    output_dir = output_root / "dataset_default_no_hint"
    shutil.rmtree(output_dir, ignore_errors=True)
    run(
        [
            sys.executable,
            "scripts/repair_multi_property.py",
            "dataset",
            "--dataset-root",
            "models/bound_modified_error_dataset",
            "--output-root",
            str(output_dir),
            "--verifyta",
            str(verifyta),
            "--families",
            "TarTarRepairedDB",
            "--limit",
            "1",
            "--max-candidates",
            "20",
            "--max-changes",
            "4",
            "--max-refinement-rounds",
            "2",
            "--timeout",
            "60",
            "--doc-output",
            str(output_root / "dataset_default_no_hint.md"),
        ],
        timeout=180,
    )
    summary = load_json(output_dir / "summary.json")
    if summary["use_mutation_hints"]:
        raise AssertionError("dataset default should not use mutation hints")
    if summary["repaired_count"] != summary["mutant_count"]:
        raise AssertionError(f"dataset smoke did not repair all selected mutants: {summary}")


def check_comparison_matrix(verifyta: Path, output_root: Path, admissibility_runner: str) -> None:
    output_dir = output_root / "comparison_matrix"
    shutil.rmtree(output_dir, ignore_errors=True)
    run(
        [
            sys.executable,
            "scripts/repair_multi_property.py",
            "comparison",
            "--dataset-root",
            "models/bound_modified_error_dataset",
            "--output-root",
            str(output_dir),
            "--verifyta",
            str(verifyta),
            "--families",
            "TarTarRepairedDB",
            "--limit",
            "1",
            "--max-candidates",
            "20",
            "--max-changes",
            "4",
            "--max-refinement-rounds",
            "2",
            "--timeout",
            "30",
            "--symbolic-use-dbm",
            "--admissibility-runner",
            admissibility_runner,
            "--admissibility-timeout",
            "60",
            "--doc-output",
            str(output_root / "comparison_matrix.md"),
        ],
        timeout=300,
    )
    comparison = load_json(output_dir / "comparison_summary.json")
    if len(comparison["variants"]) != 2:
        raise AssertionError(f"expected 2 comparison variants, got {len(comparison['variants'])}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run repair-loop smoke regression checks.")
    parser.add_argument("--verifyta", type=Path, default=DEFAULT_VERIFYTA)
    parser.add_argument("--output-root", type=Path, default=Path("experiments/repair_regression_smoke"))
    parser.add_argument("--include-comparison", action="store_true")
    parser.add_argument("--admissibility-runner", choices=["auto", "native", "wsl"], default="auto")
    args = parser.parse_args()

    compile_modules()
    check_relation_pruning()
    if not args.verifyta.exists():
        print(f"verifyta not found, skipped verifyta-dependent checks: {args.verifyta}", file=sys.stderr)
        return 0
    args.output_root.mkdir(parents=True, exist_ok=True)
    check_db_no_hint_symbolic(args.verifyta, args.output_root)
    check_dataset_default_no_hint(args.verifyta, args.output_root)
    if args.include_comparison:
        check_comparison_matrix(args.verifyta, args.output_root, args.admissibility_runner)
    print("smoke repair regression checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
