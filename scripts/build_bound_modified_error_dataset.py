#!/usr/bin/env python3
"""Generate single-fault Bound Modification mutants for the curated dataset.

The script enumerates clock-bound changes in location invariants and transition
guards, verifies every mutant, and keeps only mutants that violate at least one
property from the original property set.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.verify_automata import DEFAULT_VERIFYTA, verify_property, verify_query_file


SOURCE_ROOT = Path("models/curated_model_with_properties")
OUTPUT_ROOT = Path("models/bound_modified_error_dataset")

QUERY_START_RE = re.compile(
    r"(?P<formula>(?:A\[\]|E<>|A<>|E\[\]|sup:|inf:|Pr\[|simulate\b|control:|strategy\b).*)"
)
CLOCK_DECL_RE = re.compile(r"\bclock\s+([^;]+);", re.DOTALL)
CONST_DECL_RE = re.compile(r"\bconst\s+int(?:\s*\[[^\]]+\])?\s+([^;]+);", re.DOTALL)
CONSTRAINT_RE = re.compile(
    r"(?<![\w.])(?P<clock>[A-Za-z_]\w*)\s*(?P<op><=|>=|==|<|>)\s*"
    r"(?P<bound>-?\d+|[A-Za-z_]\w*)\b"
)


@dataclass(frozen=True)
class ModelCase:
    family: str
    version_id: str
    model_path: Path
    query_path: Path


@dataclass(frozen=True)
class BoundTarget:
    template_index: int
    template_name: str
    owner_kind: str
    owner_index: int
    owner_name: str
    label_kind: str
    label_index: int
    start: int
    end: int
    clock: str
    operator: str
    old_bound_text: str
    old_bound_value: int
    raw: str


@dataclass(frozen=True)
class Mutant:
    index: int
    target: BoundTarget
    delta: int
    new_bound: int

    @property
    def mutation_id(self) -> str:
        return f"bound_mod_{self.index:04d}"

    @property
    def new_expr(self) -> str:
        return f"{self.target.clock} {self.target.operator} {self.new_bound}"

    @property
    def description(self) -> str:
        return (
            f"{self.target.template_name}.{self.target.owner_name} "
            f"{self.target.label_kind}: {self.target.raw} -> {self.new_expr} "
            f"(delta={self.delta:+d})"
        )


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        resolved = path.resolve()
        workspace = Path.cwd().resolve()
        if not str(resolved).lower().startswith(str(workspace).lower()):
            raise RuntimeError(f"Refusing to delete outside workspace: {resolved}")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def normalize_formula(text: str) -> str:
    text = text.strip().rstrip(";")
    text = text.replace("\\\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_properties(query_path: Path) -> list[str]:
    properties: list[str] = []
    current: list[str] = []

    def flush() -> None:
        nonlocal current
        if not current:
            return
        formula = normalize_formula("\n".join(current))
        if formula:
            properties.append(formula)
        current = []

    for raw_line in read_text(query_path).splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if line.startswith("//") or line.startswith("#"):
            flush()
            continue
        match = QUERY_START_RE.search(line)
        if match:
            flush()
            current.append(match.group("formula"))
            if not line.endswith("\\"):
                flush()
            continue
        if current:
            current.append(line)
            if not line.endswith("\\"):
                flush()
    flush()
    return properties


def discover_cases(root: Path) -> list[ModelCase]:
    cases: list[ModelCase] = []
    for model_path in sorted(root.glob("*/*/model.xml")):
        rel = model_path.relative_to(root)
        family, version_id = rel.parts[0], rel.parts[1]
        query_candidates = sorted(model_path.parent.glob("*_ref.q"))
        if not query_candidates:
            continue
        cases.append(ModelCase(family, version_id, model_path, query_candidates[0]))
    return cases


def split_decl_names(text: str) -> list[str]:
    names: list[str] = []
    for part in text.split(","):
        name = re.split(r"\s*=|\[", part, maxsplit=1)[0].strip()
        if re.match(r"^[A-Za-z_]\w*$", name):
            names.append(name)
    return names


def extract_clocks(*declarations: str) -> set[str]:
    clocks: set[str] = set()
    for declaration in declarations:
        for match in CLOCK_DECL_RE.finditer(declaration or ""):
            clocks.update(split_decl_names(match.group(1)))
    return clocks


def safe_eval_int(expr: str, constants: dict[str, int]) -> int | None:
    allowed_binops = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.FloorDiv: lambda a, b: a // b,
        ast.Div: lambda a, b: a // b if b != 0 and a % b == 0 else None,
        ast.Mod: lambda a, b: a % b,
    }

    def eval_node(node: ast.AST) -> int | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return node.value
        if isinstance(node, ast.Name):
            return constants.get(node.id)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = eval_node(node.operand)
            if value is None:
                return None
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp):
            left = eval_node(node.left)
            right = eval_node(node.right)
            if left is None or right is None:
                return None
            op_fn = allowed_binops.get(type(node.op))
            return op_fn(left, right) if op_fn else None
        return None

    try:
        parsed = ast.parse(expr.strip(), mode="eval")
    except SyntaxError:
        return None
    return eval_node(parsed.body)


def extract_constants(*declarations: str) -> dict[str, int]:
    pending: dict[str, str] = {}
    for declaration in declarations:
        for match in CONST_DECL_RE.finditer(declaration or ""):
            for part in match.group(1).split(","):
                if "=" not in part:
                    continue
                name, expr = part.split("=", 1)
                name = re.split(r"\[", name, maxsplit=1)[0].strip()
                if re.match(r"^[A-Za-z_]\w*$", name):
                    pending[name] = expr.strip()

    constants: dict[str, int] = {}
    changed = True
    while changed:
        changed = False
        for name, expr in list(pending.items()):
            value = safe_eval_int(expr, constants)
            if value is not None:
                constants[name] = value
                del pending[name]
                changed = True
    return constants


def bound_value(text: str, constants: dict[str, int]) -> int | None:
    if re.match(r"^-?\d+$", text):
        return int(text)
    return constants.get(text)


def location_name(location: ET.Element, fallback: str) -> str:
    name = location.findtext("name")
    return name.strip() if name and name.strip() else fallback


def transition_name(transition: ET.Element, fallback: str) -> str:
    source = transition.find("source")
    target = transition.find("target")
    src = source.get("ref", "?") if source is not None else "?"
    tgt = target.get("ref", "?") if target is not None else "?"
    return f"{src}->{tgt}" if src or tgt else fallback


def collect_targets(root: ET.Element) -> list[BoundTarget]:
    global_decl = root.findtext("declaration") or ""
    global_constants = extract_constants(global_decl)
    global_clocks = extract_clocks(global_decl)
    targets: list[BoundTarget] = []

    for template_index, template in enumerate(root.findall("template")):
        template_name = (template.findtext("name") or f"template_{template_index}").strip()
        local_decl = template.findtext("declaration") or ""
        constants = {**global_constants, **extract_constants(local_decl)}
        clocks = global_clocks | extract_clocks(local_decl)

        for owner_index, location in enumerate(template.findall("location")):
            owner_name = location_name(location, location.get("id", f"location_{owner_index}"))
            labels = [label for label in location.findall("label") if label.get("kind") == "invariant"]
            for label_index, label in enumerate(labels):
                targets.extend(
                    find_targets_in_label(
                        label.text or "",
                        constants,
                        clocks,
                        template_index,
                        template_name,
                        "location",
                        owner_index,
                        owner_name,
                        "invariant",
                        label_index,
                    )
                )

        for owner_index, transition in enumerate(template.findall("transition")):
            owner_name = transition_name(transition, f"transition_{owner_index}")
            labels = [label for label in transition.findall("label") if label.get("kind") == "guard"]
            for label_index, label in enumerate(labels):
                targets.extend(
                    find_targets_in_label(
                        label.text or "",
                        constants,
                        clocks,
                        template_index,
                        template_name,
                        "transition",
                        owner_index,
                        owner_name,
                        "guard",
                        label_index,
                    )
                )
    return targets


def find_targets_in_label(
    text: str,
    constants: dict[str, int],
    clocks: set[str],
    template_index: int,
    template_name: str,
    owner_kind: str,
    owner_index: int,
    owner_name: str,
    label_kind: str,
    label_index: int,
) -> list[BoundTarget]:
    targets: list[BoundTarget] = []
    for match in CONSTRAINT_RE.finditer(text):
        clock = match.group("clock")
        if clock not in clocks:
            continue
        value = bound_value(match.group("bound"), constants)
        if value is None or value < 0:
            continue
        targets.append(
            BoundTarget(
                template_index=template_index,
                template_name=template_name,
                owner_kind=owner_kind,
                owner_index=owner_index,
                owner_name=owner_name,
                label_kind=label_kind,
                label_index=label_index,
                start=match.start(),
                end=match.end(),
                clock=clock,
                operator=match.group("op"),
                old_bound_text=match.group("bound"),
                old_bound_value=value,
                raw=match.group(0),
            )
        )
    return targets


def generate_mutants(targets: list[BoundTarget]) -> list[Mutant]:
    max_bound = max((target.old_bound_value for target in targets), default=1)
    deltas = sorted({-10, -1, 1, max(1, int(0.1 * max_bound)), max_bound})
    mutants: list[Mutant] = []
    for target in targets:
        for delta in deltas:
            new_bound = target.old_bound_value + delta
            if new_bound < 0 or new_bound == target.old_bound_value:
                continue
            mutants.append(Mutant(len(mutants) + 1, target, delta, new_bound))
    return mutants


def apply_mutant(root: ET.Element, mutant: Mutant) -> ET.Element:
    root_copy = ET.fromstring(ET.tostring(root, encoding="utf-8"))
    target = mutant.target
    template = root_copy.findall("template")[target.template_index]
    if target.owner_kind == "location":
        owner = template.findall("location")[target.owner_index]
    else:
        owner = template.findall("transition")[target.owner_index]
    labels = [label for label in owner.findall("label") if label.get("kind") == target.label_kind]
    label = labels[target.label_index]
    text = label.text or ""
    label.text = text[: target.start] + mutant.new_expr + text[target.end :]
    return root_copy


def write_model(root: ET.Element, path: Path) -> None:
    ET.indent(root, space="    ")
    tree = ET.ElementTree(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def verify_mutant(
    model_path: Path,
    query_path: Path,
    properties: list[str],
    verifyta: Path,
    timeout: int,
) -> tuple[str, list[dict]]:
    overall = verify_query_file(model_path, query_path, verifyta_path=verifyta, timeout=timeout)
    if overall.status != "not_satisfied":
        return (
            overall.status,
            [
                {
                    "index": 0,
                    "formula": str(query_path),
                    "status": overall.status,
                    "duration_sec": overall.duration_sec,
                    "exit_code": overall.exit_code,
                    "output_tail": overall.output[-1200:],
                }
            ],
        )

    results: list[dict] = []
    for index, formula in enumerate(properties, 1):
        result = verify_property(model_path, formula, verifyta_path=verifyta, timeout=timeout)
        results.append(
            {
                "index": index,
                "formula": formula,
                "status": result.status,
                "duration_sec": result.duration_sec,
                "exit_code": result.exit_code,
                "output_tail": result.output[-1200:],
            }
        )
    return overall.status, results


def build_for_case(
    case: ModelCase,
    output_root: Path,
    verifyta: Path,
    timeout: int,
    dry_run: bool,
    stop_after_kept: int,
) -> dict:
    root = ET.parse(case.model_path).getroot()
    properties = extract_properties(case.query_path)
    targets = collect_targets(root)
    mutants = generate_mutants(targets)
    case_out = output_root / case.family / case.version_id
    kept = []
    counters = {
        "targets": len(targets),
        "candidate_mutants": len(mutants),
        "verified_mutants": 0,
        "kept_mutants": 0,
        "non_violating_mutants": 0,
        "verification_error_mutants": 0,
    }

    if dry_run:
        return {
            "family": case.family,
            "version_id": case.version_id,
            "model": str(case.model_path),
            "properties": str(case.query_path),
            "property_count": len(properties),
            **counters,
            "mutants": kept,
        }

    case_out.mkdir(parents=True, exist_ok=True)
    write_text(case_out / "properties.q", read_text(case.query_path))

    for mutant in mutants:
        if stop_after_kept and counters["kept_mutants"] >= stop_after_kept:
            break
        tmp_model = case_out / "_candidate.xml"
        write_model(apply_mutant(root, mutant), tmp_model)
        overall_status, results = verify_mutant(tmp_model, case.query_path, properties, verifyta, timeout)
        counters["verified_mutants"] += 1
        statuses = {item["status"] for item in results}

        if overall_status == "not_satisfied" and "not_satisfied" in statuses:
            counters["kept_mutants"] += 1
            mutant_dir = case_out / mutant.mutation_id
            mutant_dir.mkdir(parents=True, exist_ok=True)
            final_model = mutant_dir / "model.xml"
            shutil.move(str(tmp_model), final_model)
            shutil.copy2(case.query_path, mutant_dir / "properties.q")
            metadata = {
                "id": mutant.mutation_id,
                "mutation_type": "bound_mod",
                "description": mutant.description,
                "source_model": str(case.model_path),
                "source_properties": str(case.query_path),
                "template": mutant.target.template_name,
                "owner_kind": mutant.target.owner_kind,
                "owner": mutant.target.owner_name,
                "label_kind": mutant.target.label_kind,
                "original": mutant.target.raw,
                "mutated": mutant.new_expr,
                "old_bound_value": mutant.target.old_bound_value,
                "old_bound_text": mutant.target.old_bound_text,
                "new_bound": mutant.new_bound,
                "delta": mutant.delta,
                "violated_properties": [
                    {"index": item["index"], "formula": item["formula"]}
                    for item in results
                    if item["status"] == "not_satisfied"
                ],
                "verification_results": results,
            }
            write_text(mutant_dir / "mutation.json", json.dumps(metadata, ensure_ascii=False, indent=2))
            kept.append(
                {
                    "id": mutant.mutation_id,
                    "path": str(final_model),
                    "description": mutant.description,
                    "violated_property_indices": [item["index"] for item in results if item["status"] == "not_satisfied"],
                }
            )
        elif overall_status == "satisfied":
            counters["non_violating_mutants"] += 1
            tmp_model.unlink(missing_ok=True)
        else:
            counters["verification_error_mutants"] += 1
            tmp_model.unlink(missing_ok=True)

        if counters["verified_mutants"] % 50 == 0:
            print(
                f"  verified={counters['verified_mutants']} "
                f"kept={counters['kept_mutants']} "
                f"errors={counters['verification_error_mutants']}",
                flush=True,
            )

    (case_out / "_candidate.xml").unlink(missing_ok=True)
    return {
        "family": case.family,
        "version_id": case.version_id,
        "model": str(case.model_path),
        "properties": str(case.query_path),
        "property_count": len(properties),
        **counters,
        "mutants": kept,
    }


def render_index(summary: dict) -> str:
    lines = [
        "# Bound Modification Error Dataset",
        "",
        "Each mutant contains exactly one clock-bound modification and is kept only if at least one original property is violated.",
        "",
        f"- Source root: `{summary['source_root']}`",
        f"- verifyta: `{summary['verifyta']}`",
        f"- Models: {summary['model_count']}",
        f"- Candidate mutants: {summary['candidate_mutants']}",
        f"- Kept violating mutants: {summary['kept_mutants']}",
        "",
        "| Family | Version | Properties | Targets | Candidates | Verified | Kept | Non-violating | Verify errors |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case in summary["cases"]:
        lines.append(
            f"| {case['family']} | {case['version_id']} | {case['property_count']} | "
            f"{case['targets']} | {case['candidate_mutants']} | {case['verified_mutants']} | "
            f"{case['kept_mutants']} | {case['non_violating_mutants']} | {case['verification_error_mutants']} |"
        )
    return "\n".join(lines) + "\n"


def build_dataset(args: argparse.Namespace) -> dict:
    source_root = args.source_root
    output_root = args.output_root
    cases = discover_cases(source_root)
    if args.families:
        selected = {item.strip() for item in args.families.split(",") if item.strip()}
        cases = [case for case in cases if case.family in selected or case.version_id in selected]
    if args.exclude_families:
        excluded = {item.strip() for item in args.exclude_families.split(",") if item.strip()}
        cases = [case for case in cases if case.family not in excluded and case.version_id not in excluded]
    if not args.dry_run:
        ensure_clean_dir(output_root)

    case_summaries = []
    for case in cases:
        print(f"[case] {case.family}/{case.version_id}", flush=True)
        case_summaries.append(
            build_for_case(
                case=case,
                output_root=output_root,
                verifyta=args.verifyta,
                timeout=args.timeout,
                dry_run=args.dry_run,
                stop_after_kept=args.stop_after_kept_per_model,
            )
        )

    summary = {
        "source_root": str(source_root),
        "output_root": str(output_root),
        "verifyta": str(args.verifyta),
        "timeout": args.timeout,
        "model_count": len(case_summaries),
        "targets": sum(item["targets"] for item in case_summaries),
        "candidate_mutants": sum(item["candidate_mutants"] for item in case_summaries),
        "verified_mutants": sum(item["verified_mutants"] for item in case_summaries),
        "kept_mutants": sum(item["kept_mutants"] for item in case_summaries),
        "non_violating_mutants": sum(item["non_violating_mutants"] for item in case_summaries),
        "verification_error_mutants": sum(item["verification_error_mutants"] for item in case_summaries),
        "cases": case_summaries,
    }
    if not args.dry_run:
        write_text(output_root / "summary.json", json.dumps(summary, ensure_ascii=False, indent=2))
        write_text(output_root / "DATASET_INDEX.md", render_index(summary))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--verifyta", type=Path, default=DEFAULT_VERIFYTA)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true", help="Only count targets and candidate mutants.")
    parser.add_argument(
        "--families",
        help="Comma-separated family or version ids to include, for example: train,mutex.",
    )
    parser.add_argument(
        "--exclude-families",
        help="Comma-separated family or version ids to skip.",
    )
    parser.add_argument(
        "--stop-after-kept-per-model",
        type=int,
        default=0,
        help="Cap kept mutants per model; 0 means keep all violating mutants.",
    )
    args = parser.parse_args()

    if not args.source_root.exists():
        raise SystemExit(f"source root not found: {args.source_root}")
    if not args.verifyta.exists():
        raise SystemExit(f"verifyta not found: {args.verifyta}")

    summary = build_dataset(args)
    print(
        json.dumps(
            {
                "models": summary["model_count"],
                "targets": summary["targets"],
                "candidate_mutants": summary["candidate_mutants"],
                "verified_mutants": summary["verified_mutants"],
                "kept_mutants": summary["kept_mutants"],
                "output": summary["output_root"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
