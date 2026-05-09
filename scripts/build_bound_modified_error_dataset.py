#!/usr/bin/env python3
"""Generate Bound Modification mutants for the curated dataset.

The script enumerates clock-bound changes in location invariants and transition
guards, applies one or more non-overlapping changes per mutant, verifies every
mutant, and keeps only mutants that violate at least one property from the
original property set.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import sys
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.admissibility.tartar_admissibility import AdmissibilityConfig, check_admissibility
from src.utils.verify_automata import DEFAULT_VERIFYTA, verify_property, verify_query_file


SOURCE_ROOT = Path("models/curated_model_with_properties")
OUTPUT_ROOT = Path("models/bound_modified_error_dataset")
DOUBLE_OUTPUT_ROOT = Path("models/bound2_dataset")

QUERY_START_RE = re.compile(
    r"(?P<formula>(?:A\[\]|E<>|A<>|E\[\]|sup:|inf:|Pr\[|simulate\b|control:|strategy\b).*)"
)
CLOCK_DECL_RE = re.compile(r"\bclock\s+([^;]+);", re.DOTALL)
INT_DECL_RE = re.compile(r"\b(?P<const>const\s+)?int(?:\s*\[[^\]]+\])?\s+(?P<body>[^;]+);", re.DOTALL)
CONSTRAINT_RE = re.compile(
    r"(?<![\w.])(?P<clock>[A-Za-z_]\w*)\s*(?P<op><=|>=|==|<|>)\s*"
    r"(?P<bound>[A-Za-z_]\w*(?:\s*[+\-]\s*(?:[A-Za-z_]\w*|-?\d+))+|[A-Za-z_]\w*|-?\d+)"
)
ASSIGN_RE = re.compile(r"(?<![<>=!])\b(?P<var>[A-Za-z_]\w*)\s*(?::=|=|\+\+|--)")


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
    old_bound_value: int | None
    raw: str
    static_bound: bool


@dataclass(frozen=True)
class Mutant:
    index: int
    target: BoundTarget
    delta: int
    new_bound: int | None

    @property
    def mutation_id(self) -> str:
        return f"bound_mod_{self.index:04d}"

    @property
    def new_bound_text(self) -> str:
        return apply_delta_to_bound_text(self.target.old_bound_text, self.delta)

    @property
    def new_expr(self) -> str:
        return f"{self.target.clock} {self.target.operator} {self.new_bound_text}"

    @property
    def description(self) -> str:
        return (
            f"{self.target.template_name}.{self.target.owner_name} "
            f"{self.target.label_kind}: {self.target.raw} -> {self.new_expr} "
            f"(delta={self.delta:+d})"
        )


@dataclass(frozen=True)
class MutationPlan:
    index: int
    mutations: tuple[Mutant, ...]

    @property
    def mutation_id(self) -> str:
        if len(self.mutations) == 1:
            return self.mutations[0].mutation_id
        return f"bound_mod_{self.index:04d}"

    @property
    def fault_count(self) -> int:
        return len(self.mutations)

    @property
    def description(self) -> str:
        if len(self.mutations) == 1:
            return self.mutations[0].description
        return "; ".join(
            f"fault_{index}: {mutation.description}"
            for index, mutation in enumerate(self.mutations, 1)
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
        declaration_text = re.sub(r"/\*.*?\*/", "", declaration or "", flags=re.DOTALL)
        declaration_text = re.sub(r"//.*", "", declaration_text)
        for match in CLOCK_DECL_RE.finditer(declaration_text):
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


def extract_assigned_variables(root: ET.Element) -> set[str]:
    return {
        match.group("var")
        for label in root.iter("label")
        if label.get("kind") == "assignment"
        for match in ASSIGN_RE.finditer(label.text or "")
    }


def extract_constants(*declarations: str, mutable_variables: set[str] | None = None) -> dict[str, int]:
    mutable_variables = mutable_variables or set()
    pending: dict[str, str] = {}
    for declaration in declarations:
        declaration_text = re.sub(r"/\*.*?\*/", "", declaration or "", flags=re.DOTALL)
        declaration_text = re.sub(r"//.*", "", declaration_text)
        for match in INT_DECL_RE.finditer(declaration_text):
            is_const = bool(match.group("const"))
            for part in match.group("body").split(","):
                if "=" not in part:
                    continue
                name, expr = part.split("=", 1)
                name = re.split(r"\[", name, maxsplit=1)[0].strip()
                if name in mutable_variables and not is_const:
                    continue
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
    text = text.strip()
    if re.match(r"^-?\d+$", text):
        return int(text)
    return safe_eval_int(text, constants)


def expression_identifiers(text: str) -> set[str]:
    return set(re.findall(r"\b[A-Za-z_]\w*\b", text or ""))


def is_supported_bound_expression(text: str, clocks: set[str]) -> bool:
    expr = text.strip()
    if not expr:
        return False
    if not re.fullmatch(r"[A-Za-z_]\w*|-?\d+|[A-Za-z_]\w*(?:\s*[+\-]\s*(?:[A-Za-z_]\w*|-?\d+))+", expr):
        return False
    # This repair fragment follows TarTar's boundary modification: the left side
    # is the clock, while the right side is a scalar bound expression.
    return not (expression_identifiers(expr) & clocks)


def apply_delta_to_bound_text(bound_text: str, delta: int) -> str:
    bound = bound_text.strip()
    if delta == 0:
        return bound
    if re.fullmatch(r"-?\d+", bound):
        return str(int(bound) + delta)
    op = "+" if delta > 0 else "-"
    return f"{bound} {op} {abs(delta)}"


def tartar_boundary_deltas(max_bound: int) -> list[int]:
    """Boundary seed faults used by TarTar's Java seed experiment.

    CorruptModel.java uses {-10, -1, +1, M/10, M}; if M <= 10, it replaces
    M by 10 and M/10 by 5. We de-duplicate equal deltas while preserving order
    to avoid writing identical mutants for small max-bound values.
    """
    bound = max_bound
    scaled = bound // 10
    if bound <= 10:
        bound = 10
        scaled = 5
    deltas: list[int] = []
    for delta in (-10, -1, 1, scaled, bound):
        if delta not in deltas:
            deltas.append(delta)
    return deltas


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
    mutable_variables = extract_assigned_variables(root)
    global_constants = extract_constants(global_decl, mutable_variables=mutable_variables)
    global_clocks = extract_clocks(global_decl)
    targets: list[BoundTarget] = []

    for template_index, template in enumerate(root.findall("template")):
        template_name = (template.findtext("name") or f"template_{template_index}").strip()
        local_decl = template.findtext("declaration") or ""
        constants = {
            **global_constants,
            **extract_constants(local_decl, mutable_variables=mutable_variables),
        }
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
        bound_text = match.group("bound").strip()
        if not is_supported_bound_expression(bound_text, clocks):
            continue
        value = bound_value(bound_text, constants)
        if value is not None and value < 0:
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
                old_bound_text=bound_text,
                old_bound_value=value,
                raw=match.group(0),
                static_bound=value is not None,
            )
        )
    return targets


def generate_mutants(targets: list[BoundTarget]) -> list[Mutant]:
    max_bound = max((target.old_bound_value for target in targets if target.old_bound_value is not None), default=0)
    deltas = tartar_boundary_deltas(max_bound)
    mutants: list[Mutant] = []
    for target in targets:
        for delta in deltas:
            new_bound = None if target.old_bound_value is None else target.old_bound_value + delta
            if delta == 0:
                continue
            mutants.append(Mutant(len(mutants) + 1, target, delta, new_bound))
    return mutants


def target_key(target: BoundTarget) -> tuple[int, str, int, str, int, int, int]:
    return (
        target.template_index,
        target.owner_kind,
        target.owner_index,
        target.label_kind,
        target.label_index,
        target.start,
        target.end,
    )


def label_key(target: BoundTarget) -> tuple[int, str, int, str, int]:
    return (
        target.template_index,
        target.owner_kind,
        target.owner_index,
        target.label_kind,
        target.label_index,
    )


def compatible_mutations(mutations: tuple[Mutant, ...]) -> bool:
    seen_targets: set[tuple[int, str, int, str, int, int, int]] = set()
    ranges_by_label: dict[tuple[int, str, int, str, int], list[tuple[int, int]]] = {}
    for mutation in mutations:
        key = target_key(mutation.target)
        if key in seen_targets:
            return False
        seen_targets.add(key)
        ranges = ranges_by_label.setdefault(label_key(mutation.target), [])
        for start, end in ranges:
            if mutation.target.start < end and start < mutation.target.end:
                return False
        ranges.append((mutation.target.start, mutation.target.end))
    return True


def generate_mutation_plans(mutants: list[Mutant], fault_count: int) -> list[MutationPlan]:
    if fault_count < 1:
        raise ValueError("fault_count must be at least 1")
    if fault_count == 1:
        return [MutationPlan(mutant.index, (mutant,)) for mutant in mutants]

    plans: list[MutationPlan] = []
    for group in combinations(mutants, fault_count):
        if compatible_mutations(group):
            plans.append(MutationPlan(len(plans) + 1, group))
    return plans


def apply_mutations(root: ET.Element, mutations: tuple[Mutant, ...]) -> ET.Element:
    root_copy = ET.fromstring(ET.tostring(root, encoding="utf-8"))
    by_label: dict[tuple[int, str, int, str, int], list[Mutant]] = {}
    for mutation in mutations:
        by_label.setdefault(label_key(mutation.target), []).append(mutation)

    for key, label_mutations in by_label.items():
        template_index, owner_kind, owner_index, label_kind, label_index = key
        template = root_copy.findall("template")[template_index]
        if owner_kind == "location":
            owner = template.findall("location")[owner_index]
        else:
            owner = template.findall("transition")[owner_index]
        labels = [label for label in owner.findall("label") if label.get("kind") == label_kind]
        label = labels[label_index]
        text = label.text or ""
        for mutation in sorted(label_mutations, key=lambda item: item.target.start, reverse=True):
            target = mutation.target
            text = text[: target.start] + mutation.new_expr + text[target.end :]
        label.text = text
    return root_copy


def apply_mutant(root: ET.Element, mutant: Mutant) -> ET.Element:
    return apply_mutations(root, (mutant,))


def apply_mutation_plan(root: ET.Element, plan: MutationPlan) -> ET.Element:
    return apply_mutations(root, plan.mutations)


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
    admissibility_config: AdmissibilityConfig,
    dry_run: bool,
    stop_after_kept: int,
    fault_count: int,
) -> dict:
    root = ET.parse(case.model_path).getroot()
    properties = extract_properties(case.query_path)
    targets = collect_targets(root)
    mutants = generate_mutants(targets)
    mutation_plans = generate_mutation_plans(mutants, fault_count)
    case_out = output_root / case.family / case.version_id
    kept = []
    counters = {
        "targets": len(targets),
        "single_fault_candidates": len(mutants),
        "candidate_mutants": len(mutation_plans),
        "verified_mutants": 0,
        "kept_mutants": 0,
        "non_violating_mutants": 0,
        "verification_error_mutants": 0,
        "admissibility_checked_mutants": 0,
        "admissible_mutants": 0,
        "inadmissible_mutants": 0,
        "admissibility_error_mutants": 0,
    }

    if dry_run:
        return {
            "family": case.family,
            "version_id": case.version_id,
            "model": str(case.model_path),
            "properties": str(case.query_path),
            "property_count": len(properties),
            "fault_count": fault_count,
            **counters,
            "mutants": kept,
        }

    case_out.mkdir(parents=True, exist_ok=True)
    write_text(case_out / "properties.q", read_text(case.query_path))

    for plan in mutation_plans:
        if stop_after_kept and counters["kept_mutants"] >= stop_after_kept:
            break
        tmp_model = case_out / "_candidate.xml"
        write_model(apply_mutation_plan(root, plan), tmp_model)
        overall_status, results = verify_mutant(tmp_model, case.query_path, properties, verifyta, timeout)
        counters["verified_mutants"] += 1
        statuses = {item["status"] for item in results}

        if overall_status == "not_satisfied" and "not_satisfied" in statuses:
            admissibility_dir = case_out / "_admissibility" / plan.mutation_id
            local_admissibility_config = AdmissibilityConfig(
                tartar_root=admissibility_config.tartar_root,
                output_dir=admissibility_dir,
                runner=admissibility_config.runner,
                timeout=admissibility_config.timeout,
                keep_transition_systems=admissibility_config.keep_transition_systems,
                verbose=admissibility_config.verbose,
            )
            admissibility = check_admissibility(case.model_path, tmp_model, local_admissibility_config)
            counters["admissibility_checked_mutants"] += 1
            if admissibility.admissible is True:
                counters["admissible_mutants"] += 1
            elif admissibility.admissible is False:
                counters["inadmissible_mutants"] += 1
                tmp_model.unlink(missing_ok=True)
                continue
            else:
                counters["admissibility_error_mutants"] += 1
                tmp_model.unlink(missing_ok=True)
                continue

            counters["kept_mutants"] += 1
            mutant_dir = case_out / plan.mutation_id
            mutant_dir.mkdir(parents=True, exist_ok=True)
            final_model = mutant_dir / "model.xml"
            shutil.move(str(tmp_model), final_model)
            shutil.copy2(case.query_path, mutant_dir / "properties.q")
            admissibility_metadata = admissibility.to_dict()
            admissibility_metadata["model_after"] = str(final_model.resolve())
            primary_mutant = plan.mutations[0]
            metadata = {
                "id": plan.mutation_id,
                "mutation_type": "bound_mod" if plan.fault_count == 1 else "bound_mod_multi",
                "fault_count": plan.fault_count,
                "description": plan.description,
                "source_model": str(case.model_path),
                "source_properties": str(case.query_path),
                "template": primary_mutant.target.template_name,
                "owner_kind": primary_mutant.target.owner_kind,
                "owner": primary_mutant.target.owner_name,
                "label_kind": primary_mutant.target.label_kind,
                "original": primary_mutant.target.raw,
                "mutated": primary_mutant.new_expr,
                "old_bound_value": primary_mutant.target.old_bound_value,
                "old_bound_text": primary_mutant.target.old_bound_text,
                "new_bound": primary_mutant.new_bound,
                "new_bound_text": primary_mutant.new_bound_text,
                "delta": primary_mutant.delta,
                "static_bound": primary_mutant.target.static_bound,
                "mutations": [
                    {
                        "index": index,
                        "single_mutation_id": mutation.mutation_id,
                        "description": mutation.description,
                        "template": mutation.target.template_name,
                        "owner_kind": mutation.target.owner_kind,
                        "owner": mutation.target.owner_name,
                        "label_kind": mutation.target.label_kind,
                        "original": mutation.target.raw,
                        "mutated": mutation.new_expr,
                        "old_bound_value": mutation.target.old_bound_value,
                        "old_bound_text": mutation.target.old_bound_text,
                        "new_bound": mutation.new_bound,
                        "new_bound_text": mutation.new_bound_text,
                        "delta": mutation.delta,
                        "static_bound": mutation.target.static_bound,
                    }
                    for index, mutation in enumerate(plan.mutations, 1)
                ],
                "violated_properties": [
                    {"index": item["index"], "formula": item["formula"]}
                    for item in results
                    if item["status"] == "not_satisfied"
                ],
                "verification_results": results,
                "admissibility": admissibility_metadata,
            }
            write_text(mutant_dir / "mutation.json", json.dumps(metadata, ensure_ascii=False, indent=2))
            kept.append(
                {
                    "id": plan.mutation_id,
                    "path": str(final_model),
                    "fault_count": plan.fault_count,
                    "description": plan.description,
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
                f"admissible={counters['admissible_mutants']} "
                f"inadmissible={counters['inadmissible_mutants']} "
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
        "fault_count": fault_count,
        **counters,
        "mutants": kept,
    }


def render_index(summary: dict) -> str:
    fault_word = "clock-bound modification" if summary["fault_count"] == 1 else "clock-bound modifications"
    lines = [
        "# Bound Modification Error Dataset",
        "",
        f"Each mutant contains exactly {summary['fault_count']} {fault_word} and is kept only if at least one original property is violated.",
        "A violating mutant is kept only when the TARTAR-style untimed equivalence check says the mutated model is functionally equivalent to the original model.",
        "",
        f"- Source root: `{summary['source_root']}`",
        f"- Fault count per mutant: {summary['fault_count']}",
        f"- Kept mutant cap per model: {summary['stop_after_kept_per_model'] or 'unbounded'}",
        f"- verifyta: `{summary['verifyta']}`",
        f"- Models: {summary['model_count']}",
        f"- Single-fault candidates: {summary['single_fault_candidates']}",
        f"- Candidate mutants: {summary['candidate_mutants']}",
        f"- Kept violating mutants: {summary['kept_mutants']}",
        f"- Admissibility checked mutants: {summary['admissibility_checked_mutants']}",
        f"- Inadmissible violating mutants discarded: {summary['inadmissible_mutants']}",
        f"- Admissibility errors discarded: {summary['admissibility_error_mutants']}",
        "",
        "| Family | Version | Properties | Faults | Targets | Single candidates | Candidates | Verified | Kept | Adm checked | Inadm | Adm errors | Non-violating | Verify errors |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case in summary["cases"]:
        lines.append(
            f"| {case['family']} | {case['version_id']} | {case['property_count']} | "
            f"{case['fault_count']} | {case['targets']} | {case['single_fault_candidates']} | "
            f"{case['candidate_mutants']} | {case['verified_mutants']} | "
            f"{case['kept_mutants']} | {case['admissibility_checked_mutants']} | "
            f"{case['inadmissible_mutants']} | {case['admissibility_error_mutants']} | "
            f"{case['non_violating_mutants']} | {case['verification_error_mutants']} |"
        )
    return "\n".join(lines) + "\n"


def build_dataset(args: argparse.Namespace) -> dict:
    source_root = args.source_root
    output_root = args.output_root or (OUTPUT_ROOT if args.fault_count == 1 else DOUBLE_OUTPUT_ROOT)
    stop_after_kept = args.stop_after_kept_per_model
    if stop_after_kept is None:
        stop_after_kept = 0 if args.fault_count == 1 else 20
    cases = discover_cases(source_root)
    if args.families:
        selected = {item.strip() for item in args.families.split(",") if item.strip()}
        cases = [case for case in cases if case.family in selected or case.version_id in selected]
    if args.exclude_families:
        excluded = {item.strip() for item in args.exclude_families.split(",") if item.strip()}
        cases = [case for case in cases if case.family not in excluded and case.version_id not in excluded]
    if not args.dry_run:
        ensure_clean_dir(output_root)
    admissibility_config = AdmissibilityConfig(
        tartar_root=args.tartar_root,
        output_dir=args.admissibility_output_dir or (output_root / "_admissibility"),
        runner=args.admissibility_runner,
        timeout=args.admissibility_timeout,
        keep_transition_systems=args.keep_admissibility_transition_systems,
    )

    case_summaries = []
    for case in cases:
        print(f"[case] {case.family}/{case.version_id}", flush=True)
        case_summaries.append(
            build_for_case(
                case=case,
                output_root=output_root,
                verifyta=args.verifyta,
                timeout=args.timeout,
                admissibility_config=admissibility_config,
                dry_run=args.dry_run,
                stop_after_kept=stop_after_kept,
                fault_count=args.fault_count,
            )
        )

    summary = {
        "source_root": str(source_root),
        "output_root": str(output_root),
        "fault_count": args.fault_count,
        "stop_after_kept_per_model": stop_after_kept,
        "verifyta": str(args.verifyta),
        "timeout": args.timeout,
        "admissibility": {
            "required_for_mutants": True,
            "tartar_root": str(admissibility_config.tartar_root),
            "runner": admissibility_config.runner,
            "timeout": admissibility_config.timeout,
            "keep_transition_systems": admissibility_config.keep_transition_systems,
        },
        "model_count": len(case_summaries),
        "targets": sum(item["targets"] for item in case_summaries),
        "single_fault_candidates": sum(item["single_fault_candidates"] for item in case_summaries),
        "candidate_mutants": sum(item["candidate_mutants"] for item in case_summaries),
        "verified_mutants": sum(item["verified_mutants"] for item in case_summaries),
        "kept_mutants": sum(item["kept_mutants"] for item in case_summaries),
        "non_violating_mutants": sum(item["non_violating_mutants"] for item in case_summaries),
        "verification_error_mutants": sum(item["verification_error_mutants"] for item in case_summaries),
        "admissibility_checked_mutants": sum(item["admissibility_checked_mutants"] for item in case_summaries),
        "admissible_mutants": sum(item["admissible_mutants"] for item in case_summaries),
        "inadmissible_mutants": sum(item["inadmissible_mutants"] for item in case_summaries),
        "admissibility_error_mutants": sum(item["admissibility_error_mutants"] for item in case_summaries),
        "cases": case_summaries,
    }
    if not args.dry_run:
        write_text(output_root / "summary.json", json.dumps(summary, ensure_ascii=False, indent=2))
        write_text(output_root / "DATASET_INDEX.md", render_index(summary))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument(
        "--output-root",
        type=Path,
        help=(
            "Output dataset root. Defaults to models/bound_modified_error_dataset "
            "for --fault-count 1 and models/bound2_dataset for --fault-count 2."
        ),
    )
    parser.add_argument(
        "--fault-count",
        type=int,
        choices=[1, 2],
        default=1,
        help="Number of non-overlapping boundary faults injected into each generated mutant.",
    )
    parser.add_argument("--verifyta", type=Path, default=DEFAULT_VERIFYTA)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--tartar-root", type=Path, default=Path("TarTar-master"))
    parser.add_argument("--admissibility-runner", choices=["auto", "native", "wsl"], default="auto")
    parser.add_argument("--admissibility-timeout", type=int, default=3600)
    parser.add_argument("--admissibility-output-dir", type=Path)
    parser.add_argument(
        "--keep-admissibility-transition-systems",
        action="store_true",
        help="Keep intermediate transition-system XML files for accepted and rejected mutants.",
    )
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
        default=None,
        help=(
            "Cap kept mutants per model. Defaults to unbounded for one-fault "
            "generation and 20 for two-fault generation; pass 0 to keep all."
        ),
    )
    args = parser.parse_args()

    if not args.source_root.exists():
        raise SystemExit(f"source root not found: {args.source_root}")
    if not args.verifyta.exists():
        raise SystemExit(f"verifyta not found: {args.verifyta}")
    if not args.tartar_root.exists():
        raise SystemExit(f"TarTar root not found: {args.tartar_root}")

    summary = build_dataset(args)
    print(
        json.dumps(
            {
                "models": summary["model_count"],
                "targets": summary["targets"],
                "fault_count": summary["fault_count"],
                "stop_after_kept_per_model": summary["stop_after_kept_per_model"],
                "single_fault_candidates": summary["single_fault_candidates"],
                "candidate_mutants": summary["candidate_mutants"],
                "verified_mutants": summary["verified_mutants"],
                "kept_mutants": summary["kept_mutants"],
                "admissibility_checked_mutants": summary["admissibility_checked_mutants"],
                "inadmissible_mutants": summary["inadmissible_mutants"],
                "admissibility_error_mutants": summary["admissibility_error_mutants"],
                "output": summary["output_root"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
