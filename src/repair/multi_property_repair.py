"""Relation-aware clock-bound repair for multi-property UPPAAL models.

The implementation is intentionally practical: it keeps the full property set
as the final oracle and searches for small clock-bound changes that make all
queries pass under verifyta.  The ranking of candidate edits follows the method
documented in ``doc/multi_property_repair_method.md``: properties, locations,
clocks and repair variables are related before candidate repairs are tried.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import re
import shutil
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field, replace
from itertools import combinations, product
from pathlib import Path
from xml.etree import ElementTree as ET

from src.admissibility.tartar_admissibility import AdmissibilityConfig, check_admissibility
from src.repair.liveness_checks import run_liveness_checks
from src.repair.property_relations import PropertyRelationReport, analyze_property_relations, strip_safety_wrapper
from src.repair.tdt_smt import (
    SymbolicBoundChange,
    collect_verifyta_traces,
    constraints_from_text,
    parse_verifyta_trace,
    solve_symbolic_repair,
)
from src.utils.verify_automata import DEFAULT_VERIFYTA, verify_property, verify_query_file


QUERY_START_RE = re.compile(
    r"(?P<formula>(?:A\[\]|E<>|A<>|E\[\]|sup:|inf:|Pr\[|simulate\b|control:|strategy\b).*)"
)
CLOCK_DECL_RE = re.compile(r"\bclock\s+([^;]+);", re.DOTALL)
INT_DECL_RE = re.compile(r"\b(?P<const>const\s+)?int(?:\s*\[[^\]]+\])?\s+(?P<body>[^;]+);", re.DOTALL)
CONSTRAINT_RE = re.compile(
    r"(?<![\w.])(?P<clock>[A-Za-z_]\w*)\s*(?P<op><=|>=|==|<|>)\s*"
    r"(?P<bound>[A-Za-z_]\w*(?:\s*[+\-]\s*(?:[A-Za-z_]\w*|-?\d+))+|[A-Za-z_]\w*|-?\d+)"
)
RESET_RE = re.compile(r"(?<![\w.])(?P<clock>[A-Za-z_]\w*)\s*:=\s*0\b")
ASSIGN_RE = re.compile(r"(?<![<>=!])\b(?P<var>[A-Za-z_]\w*)\s*(?::=|=|\+\+|--)")
INSTANCE_NAME_RE = r"[A-Za-z_]\w*(?:\(\d+\))?"
LOCATION_RE = re.compile(rf"\b(?P<template>{INSTANCE_NAME_RE})\.(?P<location>[A-Za-z_]\w*)\b")
IDENT_RE = re.compile(r"\b[A-Za-z_]\w*\b")
NUMBER_RE = re.compile(r"(?<![\w.])-?\d+\b")


@dataclass(frozen=True)
class PropertySpec:
    index: int
    formula: str
    locations: frozenset[tuple[str, str]]
    clocks: frozenset[str]
    numbers: frozenset[int]
    raw_identifiers: frozenset[str]


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
    bound_text: str
    bound_value: int | None
    raw: str
    static_bound: bool

    @property
    def key(self) -> str:
        return (
            f"{self.template_index}:{self.owner_kind}:{self.owner_index}:"
            f"{self.label_kind}:{self.label_index}:{self.start}:{self.end}"
        )

    @property
    def display_name(self) -> str:
        return f"{self.template_name}.{self.owner_name} {self.label_kind}: {self.raw}"


@dataclass(frozen=True)
class ResetTarget:
    template_index: int
    template_name: str
    transition_index: int
    transition_name: str
    label_index: int | None
    start: int | None
    end: int | None
    clock: str
    raw: str

    @property
    def key(self) -> str:
        return (
            f"{self.template_index}:reset:{self.transition_index}:"
            f"{self.label_index}:{self.start}:{self.end}:{self.clock}"
        )

    @property
    def display_name(self) -> str:
        return f"{self.template_name}.{self.transition_name} assignment: {self.raw}"


@dataclass(frozen=True)
class BoundEdit:
    target: BoundTarget
    new_bound: int | float | None
    reason: str
    relation_score: float
    new_operator: str | None = None
    new_clock: str | None = None
    delta: int | float | None = None

    @property
    def clock(self) -> str:
        return self.new_clock or self.target.clock

    @property
    def operator(self) -> str:
        return self.new_operator or self.target.operator

    @property
    def key(self) -> tuple[str, str, str, int | float | None, int | float | None]:
        return (self.target.key, self.clock, self.operator, self.new_bound, self.delta)

    @property
    def old_expr(self) -> str:
        return self.target.raw

    @property
    def new_expr(self) -> str:
        if self.delta is not None:
            bound = apply_delta_to_bound_text(self.target.bound_text, self.delta)
        elif self.new_bound is not None:
            bound = format_bound_number(self.new_bound)
        else:
            bound = self.target.bound_text
        return f"{self.clock} {self.operator} {bound}"

    @property
    def magnitude(self) -> float:
        structural_cost = 0
        if self.clock != self.target.clock:
            structural_cost += 1
        if self.operator != self.target.operator:
            structural_cost += 1
        if self.delta is not None:
            return abs(float(self.delta)) + structural_cost
        if self.new_bound is not None and self.target.bound_value is not None:
            return abs(float(self.new_bound) - self.target.bound_value) + structural_cost
        return structural_cost

    def to_dict(self) -> dict:
        return {
            "template": self.target.template_name,
            "owner_kind": self.target.owner_kind,
            "owner": self.target.owner_name,
            "label_kind": self.target.label_kind,
            "clock": self.clock,
            "operator": self.operator,
            "old_clock": self.target.clock,
            "old_operator": self.target.operator,
            "old_expr": self.old_expr,
            "new_expr": self.new_expr,
            "old_bound": self.target.bound_value,
            "old_bound_text": self.target.bound_text,
            "new_bound": self.new_bound,
            "delta": self.delta,
            "static_bound": self.target.static_bound,
            "magnitude": self.magnitude,
            "reason": self.reason,
            "relation_score": round(self.relation_score, 3),
        }


@dataclass(frozen=True)
class ResetEdit:
    target: ResetTarget
    action: str
    reason: str
    relation_score: float

    @property
    def key(self) -> tuple[str, str, str, int, int | None]:
        return (self.target.key, self.action, self.target.clock, 0, None)

    @property
    def magnitude(self) -> int:
        return 1

    def to_dict(self) -> dict:
        return {
            "template": self.target.template_name,
            "owner_kind": "transition",
            "owner": self.target.transition_name,
            "label_kind": "assignment",
            "clock": self.target.clock,
            "action": self.action,
            "old_expr": self.target.raw,
            "new_expr": "" if self.action == "delete" else f"{self.target.clock} := 0",
            "magnitude": self.magnitude,
            "reason": self.reason,
            "relation_score": round(self.relation_score, 3),
        }


RepairEdit = BoundEdit | ResetEdit


def edit_target_key(edit: RepairEdit) -> str:
    return edit.key[0]


@dataclass(frozen=True)
class CandidateRepair:
    """A concrete repair assignment produced by the symbolic TDT/Z3 layer.

    Each edit is one non-zero clock-bound variation.  The rank tuple is kept
    for report compatibility; the active research flow obtains candidates from
    Z3 rather than finite-domain enumeration.
    """

    edits: tuple[RepairEdit, ...]
    source: str
    rank: tuple[float, ...]
    symbolic_assignment: dict[str, int | float] | None = None

    @property
    def key(self) -> tuple[tuple[str, str, str, int | None, int | None], ...]:
        return tuple(sorted(edit.key for edit in self.edits))

    @property
    def target_keys(self) -> frozenset[str]:
        return frozenset(edit_target_key(edit) for edit in self.edits)

    @property
    def total_magnitude(self) -> float:
        return sum(edit.magnitude for edit in self.edits)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "changed_bounds": len(self.edits),
            "total_magnitude": self.total_magnitude,
            "rank": [round(value, 3) for value in self.rank],
            "edits": [edit.to_dict() for edit in self.edits],
            "symbolic_assignment": self.symbolic_assignment,
        }


@dataclass
class RepairRunConfig:
    verifyta: Path = DEFAULT_VERIFYTA
    timeout: int = 60
    qe_timeout: int = 500
    max_candidates: int = 300
    max_changes: int = 4
    max_refinement_rounds: int = 3
    keep_failed_candidates: bool = False
    use_mutation_hints: bool = False
    use_symbolic_smt: bool = True
    symbolic_max_bound_delta: int | None = None
    symbolic_traces_per_property: int | None = 1
    symbolic_use_dbm: bool = False
    enable_operator_repairs: bool = False
    enable_clock_repairs: bool = False
    enable_reset_repairs: bool = False
    require_liveness_checks: bool = False
    require_admissibility: bool = True
    admissibility_tartar_root: Path = Path("TarTar-master")
    admissibility_runner: str = "auto"
    admissibility_timeout: int = 3600
    admissibility_output_dir: Path | None = None


@dataclass
class RepairRunResult:
    status: str
    model: str
    properties: str
    repaired_model: str | None
    initial_status: str
    final_status: str | None
    property_count: int
    violated_properties: list[int]
    target_count: int
    candidate_count: int
    tried_candidates: int
    elapsed_sec: float
    edits: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    analysis: dict = field(default_factory=dict)
    attempts: list[dict] = field(default_factory=list)
    admissibility_status: str | None = None
    admissibility_report: str | None = None
    admissibility_counterexample: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def write_json(path: Path, data: dict) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


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
        ast.FloorDiv: lambda a, b: a // b if b else None,
        ast.Div: lambda a, b: a // b if b != 0 and a % b == 0 else None,
        ast.Mod: lambda a, b: a % b if b else None,
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
    return not (expression_identifiers(expr) & clocks)


def format_bound_number(value: int | float) -> str:
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.12g}"
    return str(value)


def apply_delta_to_bound_text(bound_text: str, delta: int | float) -> str:
    bound = bound_text.strip()
    if delta == 0:
        return bound
    if re.fullmatch(r"-?\d+", bound):
        return format_bound_number(int(bound) + delta)
    op = "+" if delta > 0 else "-"
    return f"{bound} {op} {format_bound_number(abs(delta))}"


def location_name(location: ET.Element, fallback: str) -> str:
    name = location.findtext("name")
    return name.strip() if name and name.strip() else fallback


def transition_name(transition: ET.Element, fallback: str) -> str:
    source = transition.find("source")
    target = transition.find("target")
    src = source.get("ref", "?") if source is not None else "?"
    tgt = target.get("ref", "?") if target is not None else "?"
    return f"{src}->{tgt}" if src or tgt else fallback


def parse_property(index: int, formula: str, clocks: set[str]) -> PropertySpec:
    locations = frozenset((m.group("template"), m.group("location")) for m in LOCATION_RE.finditer(formula))
    identifiers = frozenset(IDENT_RE.findall(formula))
    property_clocks = frozenset(item for item in identifiers if item in clocks)
    numbers = frozenset(int(item) for item in NUMBER_RE.findall(formula))
    return PropertySpec(index, formula, locations, property_clocks, numbers, identifiers)


def collect_targets(root: ET.Element) -> tuple[list[BoundTarget], dict[str, int], set[str]]:
    global_decl = root.findtext("declaration") or ""
    mutable_variables = extract_assigned_variables(root)
    global_constants = extract_constants(global_decl, mutable_variables=mutable_variables)
    global_clocks = extract_clocks(global_decl)
    all_constants = dict(global_constants)
    all_clocks = set(global_clocks)
    targets: list[BoundTarget] = []

    for template_index, template in enumerate(root.findall("template")):
        template_name = (template.findtext("name") or f"template_{template_index}").strip()
        local_decl = template.findtext("declaration") or ""
        local_constants = extract_constants(local_decl, mutable_variables=mutable_variables)
        constants = {**global_constants, **local_constants}
        clocks = global_clocks | extract_clocks(local_decl)
        all_constants.update(local_constants)
        all_clocks.update(clocks)

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

    return targets, all_constants, all_clocks


def collect_reset_targets(root: ET.Element, clocks: set[str]) -> tuple[list[ResetTarget], list[ResetTarget]]:
    delete_targets: list[ResetTarget] = []
    add_targets: list[ResetTarget] = []
    for template_index, template in enumerate(root.findall("template")):
        template_name = (template.findtext("name") or f"template_{template_index}").strip()
        _, template_clocks = template_environment(root, template_index)
        available_clocks = template_clocks or clocks
        for transition_index, transition in enumerate(template.findall("transition")):
            transition_display = transition_name(transition, f"transition_{transition_index}")
            assignment_labels = [
                label for label in transition.findall("label") if label.get("kind") == "assignment"
            ]
            reset_clocks: set[str] = set()
            for label_index, label in enumerate(assignment_labels):
                text = label.text or ""
                for match in RESET_RE.finditer(text):
                    clock = match.group("clock")
                    if clock not in available_clocks:
                        continue
                    reset_clocks.add(clock)
                    delete_targets.append(
                        ResetTarget(
                            template_index=template_index,
                            template_name=template_name,
                            transition_index=transition_index,
                            transition_name=transition_display,
                            label_index=label_index,
                            start=match.start(),
                            end=match.end(),
                            clock=clock,
                            raw=match.group(0),
                        )
                    )
            label_index = 0 if assignment_labels else None
            for clock in sorted(available_clocks - reset_clocks):
                add_targets.append(
                    ResetTarget(
                        template_index=template_index,
                        template_name=template_name,
                        transition_index=transition_index,
                        transition_name=transition_display,
                        label_index=label_index,
                        start=None,
                        end=None,
                        clock=clock,
                        raw="",
                    )
                )
    return delete_targets, add_targets


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
                bound_text=bound_text,
                bound_value=value,
                raw=match.group(0),
                static_bound=value is not None,
            )
        )
    return targets


def relation_score(target: BoundTarget, violated: list[PropertySpec], all_properties: list[PropertySpec]) -> tuple[float, str]:
    score = 0.0
    reasons: list[str] = []
    relevant = violated or all_properties
    target_location = (target.template_name, target.owner_name)
    for prop in relevant:
        if target_location in prop.locations:
            score += 60.0
            reasons.append(f"matches violated property location P{prop.index}")
        elif any(template == target.template_name for template, _ in prop.locations):
            score += 25.0
            reasons.append(f"matches violated property template P{prop.index}")
        if target.clock in prop.clocks:
            score += 35.0
            reasons.append(f"matches violated property clock P{prop.index}")
        if target.owner_name in prop.raw_identifiers:
            score += 20.0
            reasons.append(f"mentions owner in P{prop.index}")
    if target.label_kind == "invariant":
        score += 4.0
    if target.operator in {"<=", "<", "=="}:
        score += 2.0
    if not reasons:
        reasons.append("fallback global bound candidate")
    return score, "; ".join(dict.fromkeys(reasons))


def candidate_values_for_target(
    target: BoundTarget,
    targets: list[BoundTarget],
    constants: dict[str, int],
    properties: list[PropertySpec],
) -> list[int]:
    if target.bound_value is None:
        return []
    current = target.bound_value
    values: set[int] = set()

    # Local neighborhood. This catches small injected +/-1 and +/-5 faults.
    for delta in [1, 2, 3, 4, 5, 10, 20, 50, 100]:
        values.add(current - delta)
        values.add(current + delta)

    if current > 0:
        scale_steps = {
            max(1, current // 20),
            max(1, current // 10),
            max(1, current // 5),
            max(1, current // 2),
        }
        for step in scale_steps:
            values.add(current - step)
            values.add(current + step)

    # Values already used for the same clock are often the intended repair
    # value in mutation-based datasets and in hand-written models.
    for other in targets:
        if other.key == target.key:
            continue
        if other.bound_value is None:
            continue
        if other.clock == target.clock:
            values.add(other.bound_value)
        if other.operator == target.operator:
            values.add(other.bound_value)

    values.update(constants.values())
    for prop in properties:
        values.update(prop.numbers)

    if target.operator in {"<=", "<"}:
        values.update(value for value in range(max(0, current - 8), current))
    elif target.operator in {">=", ">"}:
        values.update(value for value in range(current + 1, current + 9))
    else:
        values.update(value for value in range(max(0, current - 5), current + 6))

    filtered = [value for value in values if value >= 0 and value != current]
    if target.operator in {"<=", "<"}:
        filtered.sort(key=lambda value: (value > current, abs(value - current), value))
    elif target.operator in {">=", ">"}:
        filtered.sort(key=lambda value: (value < current, abs(value - current), value))
    else:
        filtered.sort(key=lambda value: (abs(value - current), value))
    return filtered[:40]


def generate_candidate_edits(
    targets: list[BoundTarget],
    constants: dict[str, int],
    properties: list[PropertySpec],
    violated: list[PropertySpec],
    max_candidates: int,
) -> list[BoundEdit]:
    candidates: list[BoundEdit] = []
    for target in targets:
        score, reason = relation_score(target, violated, properties)
        for value in candidate_values_for_target(target, targets, constants, properties):
            value_penalty = math.log1p(abs(value - target.bound_value))
            direction_bonus = 0.0
            if target.operator in {"<=", "<"} and value < target.bound_value:
                direction_bonus = 3.0
            elif target.operator in {">=", ">"} and value > target.bound_value:
                direction_bonus = 3.0
            elif target.operator == "==":
                direction_bonus = 1.0
            candidates.append(
                BoundEdit(
                    target=target,
                    new_bound=value,
                    reason=reason,
                    relation_score=score + direction_bonus - value_penalty,
                )
            )

    candidates.sort(
        key=lambda edit: (
            -edit.relation_score,
            edit.magnitude,
            edit.target.template_index,
            edit.target.owner_index,
            edit.target.label_index,
        )
    )

    deduped: list[BoundEdit] = []
    seen: set[tuple[str, str, str, int | None, int | None]] = set()
    for edit in candidates:
        if edit.key in seen:
            continue
        seen.add(edit.key)
        deduped.append(edit)
        if len(deduped) >= max_candidates:
            break
    return deduped


def generate_operator_candidate_edits(
    targets: list[BoundTarget],
    properties: list[PropertySpec],
    violated: list[PropertySpec],
) -> list[BoundEdit]:
    """Generate small comparison-operator repairs.

    These candidates are deliberately conservative: they only change the
    comparator at the same syntactic bound and rely on full verification to
    decide whether the strengthened/weakened semantics is acceptable.
    """

    variants = {
        "<=": ["<", "=="],
        "<": ["<="],
        ">=": [">", "=="],
        ">": [">="],
        "==": ["<=", ">="],
    }
    candidates: list[BoundEdit] = []
    for target in targets:
        score, reason = relation_score(target, violated, properties)
        for operator in variants.get(target.operator, []):
            candidates.append(
                BoundEdit(
                    target=target,
                    new_bound=target.bound_value,
                    reason=f"{reason}; comparison-operator repair",
                    relation_score=score - 8.0,
                    new_operator=operator,
                )
            )
    return candidates


def generate_clock_reference_candidate_edits(
    targets: list[BoundTarget],
    clocks: set[str],
    properties: list[PropertySpec],
    violated: list[PropertySpec],
) -> list[BoundEdit]:
    """Generate same-bound clock-reference substitutions.

    Clock-reference mutations are rare but damaging.  The ranking prefers
    clocks mentioned by violated properties and otherwise keeps the candidate
    set small by trying only clocks that already appear in the model.
    """

    relevant_clocks = {
        clock
        for prop in (violated or properties)
        for clock in prop.clocks
    } or set(clocks)
    candidates: list[BoundEdit] = []
    for target in targets:
        score, reason = relation_score(target, violated, properties)
        for clock in sorted(relevant_clocks | {other.clock for other in targets if other.template_name == target.template_name}):
            if clock == target.clock or clock not in clocks:
                continue
            candidates.append(
                BoundEdit(
                    target=target,
                    new_bound=target.bound_value,
                    reason=f"{reason}; clock-reference repair",
                    relation_score=score - 12.0 + (4.0 if clock in relevant_clocks else 0.0),
                    new_clock=clock,
                )
            )
    return candidates


def reset_relation_score(target: ResetTarget, violated: list[PropertySpec], all_properties: list[PropertySpec]) -> tuple[float, str]:
    score = 0.0
    reasons: list[str] = []
    for prop in (violated or all_properties):
        if any(template == target.template_name for template, _ in prop.locations):
            score += 20.0
            reasons.append(f"matches violated property template P{prop.index}")
        if target.clock in prop.clocks:
            score += 35.0
            reasons.append(f"matches violated property clock P{prop.index}")
        if target.transition_name in prop.raw_identifiers:
            score += 10.0
            reasons.append(f"mentions transition in P{prop.index}")
    if not reasons:
        reasons.append("fallback reset candidate")
    return score, "; ".join(dict.fromkeys(reasons))


def generate_reset_candidate_edits(
    root: ET.Element,
    clocks: set[str],
    properties: list[PropertySpec],
    violated: list[PropertySpec],
) -> list[ResetEdit]:
    delete_targets, add_targets = collect_reset_targets(root, clocks)
    relevant_clocks = {clock for prop in (violated or properties) for clock in prop.clocks}
    candidates: list[ResetEdit] = []
    for target in delete_targets:
        score, reason = reset_relation_score(target, violated, properties)
        candidates.append(
            ResetEdit(
                target=target,
                action="delete",
                reason=f"{reason}; reset deletion",
                relation_score=score - 10.0,
            )
        )
    for target in add_targets:
        if relevant_clocks and target.clock not in relevant_clocks:
            continue
        score, reason = reset_relation_score(target, violated, properties)
        candidates.append(
            ResetEdit(
                target=target,
                action="add",
                reason=f"{reason}; reset insertion",
                relation_score=score - 6.0,
            )
        )
    return candidates


def symbolic_change_to_edit(change: SymbolicBoundChange, targets: list[BoundTarget]) -> BoundEdit | None:
    def template_base(name: str) -> str:
        return re.sub(r"\(\d+\)$", "", name)

    change_template_base = template_base(change.template)

    def same_clock(target_clock: str, change_clock: str) -> bool:
        return target_clock == change_clock or change_clock.endswith(f".{target_clock}")

    def find_matches(require_original_bound: bool) -> list[BoundTarget]:
        found = [
            target
            for target in targets
            if (
                target.template_name == change.template
                or target.template_name == change_template_base
            )
            and target.owner_kind == change.owner_kind
            and target.label_kind == change.label_kind
            and same_clock(target.clock, change.clock)
            and target.operator == change.operator
            and (
                not require_original_bound
                or target.bound_value is None
                or target.bound_value == change.old_bound
            )
        ]
        if change.owner_name:
            named = [target for target in found if target.owner_name == change.owner_name]
            if named:
                found = named
        return found

    matches = find_matches(require_original_bound=True)
    relaxed_bound_match = False
    if len(matches) != 1:
        relaxed = find_matches(require_original_bound=False)
        if len(relaxed) == 1:
            matches = relaxed
            relaxed_bound_match = True
    if len(matches) != 1:
        return None
    reason = f"Z3 TDT {change.action} repair from {change.site_key}"
    if relaxed_bound_match:
        reason += "; mapped by syntactic site because trace was collected from a refined candidate"
    return BoundEdit(
        target=matches[0],
        new_bound=change.new_bound,
        reason=reason,
        relation_score=900000.0,
        new_operator=change.new_operator,
        new_clock=change.new_clock,
        delta=change.delta if change.action == "bound" else None,
    )


def symbolic_changes_to_candidate_repairs(
    changes: list[SymbolicBoundChange],
    targets: list[BoundTarget],
    properties: list[PropertySpec],
    violated: list[PropertySpec],
) -> tuple[list[CandidateRepair], list[str]]:
    edits: list[BoundEdit] = []
    notes: list[str] = []
    symbolic_assignment: dict[str, int | float] = {}
    for change in changes:
        if change.action != "bound":
            notes.append(f"ignored non-bound symbolic repair action in clock-bound-only mode: {change.site_key}")
            continue
        edit = symbolic_change_to_edit(change, targets)
        if edit is None:
            notes.append(f"could not map symbolic repair site to model target: {change.site_key}")
            continue
        edits.append(edit)
        symbolic_assignment[change.site_key] = change.delta
    if not edits:
        return [], notes
    edits = dedupe_edits(edits)
    candidate = CandidateRepair(
        edits=tuple(edits),
        source="tdt_z3_symbolic",
        rank=(-1.0, 0.0, float(sum(edit.magnitude for edit in edits)), 0.0, -999999.0, -999999.0),
        symbolic_assignment=symbolic_assignment,
    )
    return [candidate], notes


def relation_pruned_symbolic_indices(
    indices: set[int] | list[int] | tuple[int, ...],
    relations: PropertyRelationReport | None,
) -> tuple[list[int], list[str]]:
    """Select the property representatives used for local TDT encoding.

    The final verifyta pass still checks the full property file.  This function
    only removes formula-level redundancy from the local symbolic repair task.
    """

    selected = set(indices)
    notes: list[str] = []
    if not relations or not selected:
        return sorted(selected), notes

    representative: dict[int, int] = {}
    for group in relations.equivalent_groups:
        if not group:
            continue
        rep = min(group)
        for index in group:
            representative[index] = rep

    replaced: dict[int, int] = {}
    normalized: set[int] = set()
    for index in selected:
        rep = representative.get(index, index)
        normalized.add(rep)
        if rep != index:
            replaced[index] = rep
    if replaced:
        notes.append(
            "symbolic TDT encoding used equivalent representative(s): "
            + ", ".join(f"P{old}->P{new}" for old, new in sorted(replaced.items()))
        )

    removed_by_implication: list[tuple[int, int]] = []
    for implication in relations.implications:
        stronger = representative.get(implication["stronger"], implication["stronger"])
        weaker = representative.get(implication["weaker"], implication["weaker"])
        if stronger == weaker:
            continue
        if stronger in normalized and weaker in normalized:
            normalized.remove(weaker)
            removed_by_implication.append((stronger, weaker))
    if removed_by_implication:
        notes.append(
            "symbolic TDT encoding omitted weaker implied propert"
            f"{'y' if len(removed_by_implication) == 1 else 'ies'}: "
            + ", ".join(f"P{stronger}=>P{weaker}" for stronger, weaker in removed_by_implication)
        )

    return sorted(normalized), notes


TraceSiteKey = tuple[str, str, str, str, str]


def trace_site_coverage(trace_paths: list[Path]) -> dict[TraceSiteKey, int]:
    coverage: dict[TraceSiteKey, int] = {}
    for trace_path in trace_paths:
        try:
            trace = parse_verifyta_trace(trace_path, 0, "")
        except Exception:
            continue
        sites_in_trace: set[TraceSiteKey] = set()
        visited_locations = {trace.initial_node}
        for step in trace.steps:
            visited_locations.add(step.source)
            visited_locations.add(step.target)
        visited_location_ids: set[str] = set()
        for node_id in visited_locations:
            node = trace.nodes.get(node_id)
            if node is not None:
                visited_location_ids.update(node.locations)
        for location_id in visited_location_ids:
            location = trace.locations.get(location_id)
            if location is None:
                continue
            template = location.id.split(".", 1)[0] if "." in location.id else location.process
            for site in constraints_from_text(
                location.invariant,
                owner_id=location.id,
                owner_kind="location",
                owner_name=location.name,
                label_kind="invariant",
            ):
                sites_in_trace.add((template, site.owner_kind, site.owner_name, site.label_kind, site.clock))
        for step in trace.steps:
            for edge_id in step.edge_ids:
                edge = trace.edges.get(edge_id)
                if edge is None:
                    continue
                template = edge.id.split(".", 1)[0] if "." in edge.id else edge.process
                for site in constraints_from_text(
                    edge.guard,
                    owner_id=edge.id,
                    owner_kind="transition",
                    owner_name=edge.owner_name,
                    label_kind="guard",
                ):
                    sites_in_trace.add((template, site.owner_kind, site.owner_name, site.label_kind, site.clock))
        for site_key in sites_in_trace:
            coverage[site_key] = coverage.get(site_key, 0) + 1
    return coverage


def apply_trace_coverage_bonus(edits: list[RepairEdit], coverage: dict[TraceSiteKey, int]) -> list[RepairEdit]:
    if not coverage:
        return edits
    updated: list[RepairEdit] = []
    for edit in edits:
        if not isinstance(edit, BoundEdit):
            updated.append(edit)
            continue
        key = (
            edit.target.template_name,
            edit.target.owner_kind,
            edit.target.owner_name,
            edit.target.label_kind,
            edit.clock,
        )
        count = coverage.get(key, 0)
        if count <= 0:
            updated.append(edit)
            continue
        updated.append(
            replace(
                edit,
                reason=f"{edit.reason}; appears in {count} collected TDT(s)",
                relation_score=edit.relation_score + 45.0 * count,
            )
        )
    return updated


def canonical_property_formula(formula: str) -> str:
    return re.sub(r"\s+", "", formula.strip().rstrip(";")).lower()


def target_property_overlap(target: BoundTarget, prop: PropertySpec) -> int:
    overlap = 0
    if (target.template_name, target.owner_name) in prop.locations:
        overlap += 4
    elif any(template == target.template_name for template, _ in prop.locations):
        overlap += 2
    if target.clock in prop.clocks:
        overlap += 3
    if target.owner_name in prop.raw_identifiers:
        overlap += 1
    return overlap


def build_dependency_components(
    targets: list[BoundTarget],
    properties: list[PropertySpec],
) -> tuple[dict[str, int], list[dict]]:
    parent = {target.key: target.key for target in targets}

    def find(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for prop in properties:
        related = [
            target.key
            for target in targets
            if target_property_overlap(target, prop) > 0
        ]
        for key in related[1:]:
            union(related[0], key)

    by_clock: dict[tuple[str, str], list[str]] = {}
    for target in targets:
        by_clock.setdefault((target.template_name, target.clock), []).append(target.key)
    for keys in by_clock.values():
        for key in keys[1:]:
            union(keys[0], key)

    grouped: dict[str, list[BoundTarget]] = {}
    for target in targets:
        grouped.setdefault(find(target.key), []).append(target)

    ordered_roots = sorted(grouped, key=lambda root: (-len(grouped[root]), root))
    component_ids = {root: index for index, root in enumerate(ordered_roots, 1)}
    target_to_component = {
        target.key: component_ids[find(target.key)]
        for target in targets
    }
    reports = []
    for root in ordered_roots:
        component_targets = sorted(grouped[root], key=lambda target: target.display_name)
        component_properties = sorted(
            {
                prop.index
                for prop in properties
                for target in component_targets
                if target_property_overlap(target, prop) > 0
            }
        )
        reports.append(
            {
                "component": component_ids[root],
                "size": len(component_targets),
                "templates": sorted({target.template_name for target in component_targets}),
                "clocks": sorted({target.clock for target in component_targets}),
                "properties": component_properties,
                "targets": [target.display_name for target in component_targets[:12]],
            }
        )
    return target_to_component, reports


def analyze_search_space(
    targets: list[BoundTarget],
    properties: list[PropertySpec],
    violated: list[PropertySpec],
) -> dict:
    canonical_groups: dict[str, list[int]] = {}
    for prop in properties:
        canonical_groups.setdefault(canonical_property_formula(prop.formula), []).append(prop.index)
    equivalent_groups = [indices for indices in canonical_groups.values() if len(indices) > 1]

    related_pairs = 0
    for left, right in combinations(properties, 2):
        if left.locations & right.locations or left.clocks & right.clocks:
            related_pairs += 1

    target_to_component, component_reports = build_dependency_components(targets, properties)

    relevant_props = violated or properties
    target_summaries = []
    for target in targets:
        coverage = sum(1 for prop in relevant_props if target_property_overlap(target, prop) > 0)
        if coverage:
            target_summaries.append(
                {
                    "target": target.display_name,
                    "clock": target.clock,
                    "coverage": coverage,
                }
            )
    target_summaries.sort(key=lambda item: (-item["coverage"], item["target"]))

    return {
        "property_count": len(properties),
        "violated_property_count": len(violated),
        "equivalent_property_groups": equivalent_groups,
        "related_property_pairs": related_pairs,
        "repair_variable_count": len(targets),
        "dependency_component_count": len(component_reports),
        "largest_dependency_component": max((item["size"] for item in component_reports), default=0),
        "dependency_components": component_reports,
        "target_dependency_component": target_to_component,
        "top_repair_variables": target_summaries[:10],
    }


def analyze_reachable_property_relations(
    model_path: Path,
    formulas: list[str],
    verifyta: Path,
    timeout: int,
    max_pairs: int = 24,
) -> dict:
    bodies: dict[int, str] = {}
    unsupported: dict[int, str] = {}
    for index, formula in enumerate(formulas, 1):
        text = formula.strip().rstrip(";")
        if not text.startswith("A[]"):
            unsupported[index] = "only A[] safety formulas are checked for reachable-state relations"
            continue
        body = strip_safety_wrapper(text)
        if not body:
            unsupported[index] = "empty safety body"
            continue
        bodies[index] = body

    implications: list[dict] = []
    conflicts: list[dict] = []
    query_results: list[dict] = []
    checked_pairs = 0
    for left_index, right_index in combinations(sorted(bodies), 2):
        if checked_pairs >= max_pairs:
            break
        left = bodies[left_index]
        right = bodies[right_index]
        implication_lr = f"A[] (not ({left}) or ({right}))"
        implication_rl = f"A[] (not ({right}) or ({left}))"
        conflict_query = f"A[] not (({left}) and ({right}))"
        lr_result = verify_property(model_path, implication_lr, verifyta_path=verifyta, timeout=timeout)
        rl_result = verify_property(model_path, implication_rl, verifyta_path=verifyta, timeout=timeout)
        conflict_result = verify_property(model_path, conflict_query, verifyta_path=verifyta, timeout=timeout)
        checked_pairs += 1
        query_results.append(
            {
                "properties": [left_index, right_index],
                "left_implies_right": lr_result.status,
                "right_implies_left": rl_result.status,
                "conflict": conflict_result.status,
            }
        )
        if lr_result.satisfied:
            implications.append(
                {
                    "stronger": left_index,
                    "weaker": right_index,
                    "scope": "reachable_states_current_model",
                }
            )
        if rl_result.satisfied:
            implications.append(
                {
                    "stronger": right_index,
                    "weaker": left_index,
                    "scope": "reachable_states_current_model",
                }
            )
        if conflict_result.satisfied:
            conflicts.append(
                {
                    "properties": [left_index, right_index],
                    "scope": "reachable_states_current_model",
                    "reason": "A[] not (phi_i and phi_j) is satisfied on the current model",
                }
            )

    parent = {index: index for index in bodies}

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    implication_pairs = {(item["stronger"], item["weaker"]) for item in implications}
    for left, right in combinations(sorted(bodies), 2):
        if (left, right) in implication_pairs and (right, left) in implication_pairs:
            parent[find(right)] = find(left)
    groups: dict[int, list[int]] = {}
    for index in bodies:
        groups.setdefault(find(index), []).append(index)

    notes = [
        "reachable-state relations are checked on the current model with verifyta and are reported only; "
        "they are not used as sound pruning assumptions after repair"
    ]
    if len(bodies) * max(0, len(bodies) - 1) // 2 > checked_pairs:
        notes.append(f"reachable relation checks capped at {checked_pairs} pair(s)")
    return {
        "scope": "reachable_states_current_model",
        "checked_pairs": checked_pairs,
        "implications": implications,
        "equivalent_groups": [sorted(group) for group in groups.values() if len(group) > 1],
        "conflicts": conflicts,
        "unsupported": unsupported,
        "query_results": query_results,
        "notes": notes,
    }


def edit_risk(edit: RepairEdit, properties: list[PropertySpec]) -> float:
    if isinstance(edit, ResetEdit):
        risk = 2.4
        if edit.action == "delete":
            risk += 0.8
        if any(edit.target.clock in prop.clocks for prop in properties):
            risk += 0.4
        return risk
    risk = 1.0
    if edit.target.label_kind == "invariant":
        risk += 1.5
    if edit.operator == "==":
        risk += 1.0
    if edit.new_bound is not None and edit.target.bound_value is not None:
        if edit.operator in {"<=", "<"} and edit.new_bound < edit.target.bound_value:
            risk += 0.8
        if edit.operator in {">=", ">"} and edit.new_bound > edit.target.bound_value:
            risk += 0.8
    if edit.operator != edit.target.operator:
        risk += 1.2
    if edit.clock != edit.target.clock:
        risk += 1.5
    if any(target_property_overlap(edit.target, prop) >= 4 for prop in properties):
        risk += 0.4
    return risk


def edit_benefit(edit: RepairEdit, violated: list[PropertySpec], all_properties: list[PropertySpec]) -> float:
    relevant = violated or all_properties
    if isinstance(edit, ResetEdit):
        coverage = 0
        for prop in relevant:
            if any(template == edit.target.template_name for template, _ in prop.locations):
                coverage += 2
            if edit.target.clock in prop.clocks:
                coverage += 3
        return coverage + max(0.0, edit.relation_score / 20.0)
    coverage = sum(target_property_overlap(edit.target, prop) for prop in relevant)
    return coverage + max(0.0, edit.relation_score / 20.0)


def candidate_rank(
    edits: tuple[RepairEdit, ...],
    violated: list[PropertySpec],
    all_properties: list[PropertySpec],
) -> tuple[float, ...]:
    changed_count = float(len(edits))
    hint_priority = 0.0 if any(edit.reason.startswith("dataset mutation hint") for edit in edits) else 1.0
    magnitude = float(sum(edit.magnitude for edit in edits))
    risk = sum(edit_risk(edit, all_properties) for edit in edits)
    benefit = sum(edit_benefit(edit, violated, all_properties) for edit in edits)
    relation = sum(edit.relation_score for edit in edits)
    return (changed_count, hint_priority, magnitude, risk, -benefit, -relation)


def dedupe_edits(edits: list[RepairEdit]) -> list[RepairEdit]:
    deduped: list[RepairEdit] = []
    seen: set[tuple[str, str, str, int | None, int | None]] = set()
    for edit in edits:
        if edit.key in seen:
            continue
        seen.add(edit.key)
        deduped.append(edit)
    return deduped


def edits_are_compatible(edits: tuple[RepairEdit, ...]) -> bool:
    target_keys = [edit_target_key(edit) for edit in edits]
    return len(target_keys) == len(set(target_keys))


def model_bounds_consistent(root: ET.Element) -> tuple[bool, str | None]:
    for template_index, template in enumerate(root.findall("template")):
        constants, clocks = template_environment(root, template_index)
        owners = list(template.findall("location")) + list(template.findall("transition"))
        for owner in owners:
            owner_name = (
                location_name(owner, owner.get("id", "location"))
                if owner.tag == "location"
                else transition_name(owner, "transition")
            )
            for label in owner.findall("label"):
                if label.get("kind") not in {"invariant", "guard"}:
                    continue
                by_clock: dict[str, dict[str, tuple[int, bool]]] = {}
                for clock, op, value in constraints_in_label(label.text or "", constants, clocks):
                    bounds = by_clock.setdefault(clock, {})
                    if op in {">=", ">"}:
                        strict = op == ">"
                        previous = bounds.get("lower")
                        if previous is None or value > previous[0] or (value == previous[0] and strict):
                            bounds["lower"] = (value, strict)
                    elif op in {"<=", "<"}:
                        strict = op == "<"
                        previous = bounds.get("upper")
                        if previous is None or value < previous[0] or (value == previous[0] and strict):
                            bounds["upper"] = (value, strict)
                    elif op == "==":
                        bounds["lower"] = (value, False)
                        bounds["upper"] = (value, False)
                for clock, bounds in by_clock.items():
                    lower = bounds.get("lower")
                    upper = bounds.get("upper")
                    if lower is None or upper is None:
                        continue
                    if lower[0] > upper[0] or (lower[0] == upper[0] and (lower[1] or upper[1])):
                        return False, f"inconsistent bounds for {clock} in {owner_name}: lower {lower}, upper {upper}"
    return True, None


def combined_static_admissible(root: ET.Element, edits: tuple[RepairEdit, ...]) -> tuple[bool, str | None]:
    for edit in edits:
        if isinstance(edit, ResetEdit):
            continue
        ok, reason = static_admissible_edit(root, edit)
        if not ok:
            return ok, reason
    candidate_root = apply_edits(root, list(edits))
    return model_bounds_consistent(candidate_root)


def _candidate_with_source(candidate: CandidateRepair, source: str) -> CandidateRepair:
    return CandidateRepair(
        edits=candidate.edits,
        source=source,
        rank=candidate.rank,
        symbolic_assignment=candidate.symbolic_assignment,
    )


def _component_for_edit(edit: RepairEdit, target_components: dict[str, int] | None) -> str:
    if isinstance(edit, BoundEdit) and target_components and edit.target.key in target_components:
        return f"C{target_components[edit.target.key]}"
    if isinstance(edit, BoundEdit):
        return f"target:{edit.target.key}"
    return f"reset:{edit.target.template_name}:{edit.target.clock}"


def _generate_candidate_repairs_flat(
    root: ET.Element,
    edits: list[RepairEdit],
    properties: list[PropertySpec],
    violated: list[PropertySpec],
    max_candidates: int,
    max_changes: int,
) -> tuple[list[CandidateRepair], int]:
    max_changes = max(1, max_changes)
    single_repairs: list[CandidateRepair] = []
    combo_repairs: list[CandidateRepair] = []
    seen: set[tuple[tuple[str, str, str, int | None, int | None], ...]] = set()
    skipped_static = 0

    def add_repair(combo: tuple[RepairEdit, ...], source: str) -> None:
        nonlocal skipped_static
        if not edits_are_compatible(combo):
            return
        key = tuple(sorted(edit.key for edit in combo))
        if key in seen:
            return
        ok, _reason = combined_static_admissible(root, combo)
        if not ok:
            skipped_static += 1
            return
        seen.add(key)
        candidate = CandidateRepair(
            edits=combo,
            source=source,
            rank=candidate_rank(combo, violated, properties),
        )
        if len(combo) == 1:
            single_repairs.append(candidate)
        else:
            combo_repairs.append(candidate)

    for edit in edits:
        source = "single_reset_repair" if isinstance(edit, ResetEdit) else "single_bound_variation"
        add_repair((edit,), source)

    if max_changes >= 2:
        seed_limit = min(len(edits), 48 if max_changes == 2 else 28)
        seeds = edits[:seed_limit]
        for size in range(2, max_changes + 1):
            for combo in combinations(seeds, size):
                mixed = any(isinstance(edit, ResetEdit) for edit in combo)
                add_repair(tuple(combo), f"{size}_{'mixed' if mixed else 'bound'}_variation")

    single_repairs.sort(key=lambda candidate: candidate.rank)
    combo_repairs.sort(key=lambda candidate: candidate.rank)
    if max_changes == 1 or not combo_repairs:
        repairs = single_repairs[:max_candidates]
    else:
        single_budget = min(len(single_repairs), max(8, max_candidates // 2))
        combo_budget = max_candidates - single_budget
        repairs = single_repairs[:single_budget] + combo_repairs[:combo_budget]
        repairs.sort(key=lambda candidate: candidate.rank)
    return repairs[:max_candidates], skipped_static


def generate_candidate_repairs(
    root: ET.Element,
    edits: list[RepairEdit],
    properties: list[PropertySpec],
    violated: list[PropertySpec],
    max_candidates: int,
    max_changes: int,
    target_components: dict[str, int] | None = None,
) -> tuple[list[CandidateRepair], int, dict]:
    flat_repairs, skipped_static = _generate_candidate_repairs_flat(
        root,
        edits,
        properties,
        violated,
        max_candidates,
        max_changes,
    )
    if not target_components:
        return flat_repairs, skipped_static, {
            "enabled": False,
            "reason": "no dependency component map",
            "flat_candidate_count": len(flat_repairs),
        }

    by_component: dict[str, list[RepairEdit]] = {}
    for edit in edits:
        by_component.setdefault(_component_for_edit(edit, target_components), []).append(edit)

    component_repairs: dict[str, list[CandidateRepair]] = {}
    component_budget = max(4, max_candidates // max(1, len(by_component)))
    local_candidate_count = 0
    for component, component_edits in sorted(by_component.items()):
        local, skipped = _generate_candidate_repairs_flat(
            root,
            component_edits,
            properties,
            violated,
            component_budget,
            max_changes,
        )
        skipped_static += skipped
        component_repairs[component] = [
            _candidate_with_source(candidate, f"component_{component}_{candidate.source}")
            for candidate in local
        ]
        local_candidate_count += len(local)

    merged_candidates: list[CandidateRepair] = []
    seen: set[tuple[tuple[str, str, str, int | None, int | None], ...]] = set(candidate.key for candidate in flat_repairs)

    def add_merged(edits_tuple: tuple[RepairEdit, ...], source: str) -> None:
        nonlocal skipped_static
        if len(edits_tuple) > max_changes or not edits_are_compatible(edits_tuple):
            return
        key = tuple(sorted(edit.key for edit in edits_tuple))
        if key in seen:
            return
        ok, _reason = combined_static_admissible(root, edits_tuple)
        if not ok:
            skipped_static += 1
            return
        seen.add(key)
        merged_candidates.append(
            CandidateRepair(
                edits=edits_tuple,
                source=source,
                rank=candidate_rank(edits_tuple, violated, properties),
            )
        )

    component_items = [
        (component, candidates[: min(4, len(candidates))])
        for component, candidates in component_repairs.items()
        if candidates
    ]
    if max_changes >= 2 and len(component_items) >= 2:
        max_components = min(max_changes, len(component_items))
        for size in range(2, max_components + 1):
            for component_subset in combinations(component_items, size):
                component_names = [name for name, _candidates in component_subset]
                for local_tuple in product(*(candidates for _name, candidates in component_subset)):
                    edits_tuple = tuple(edit for candidate in local_tuple for edit in candidate.edits)
                    add_merged(edits_tuple, f"component_merge_{'+'.join(component_names)}")

    combined: list[CandidateRepair] = []
    combined_seen: set[tuple[tuple[str, str, str, int | None, int | None], ...]] = set()
    for candidate in [
        *(candidate for candidates in component_repairs.values() for candidate in candidates),
        *merged_candidates,
        *flat_repairs,
    ]:
        if candidate.key in combined_seen:
            continue
        combined_seen.add(candidate.key)
        combined.append(candidate)
    combined.sort(key=lambda candidate: candidate.rank)
    summary = {
        "enabled": True,
        "component_count": len(by_component),
        "local_subproblem_count": len(component_repairs),
        "local_candidate_count": local_candidate_count,
        "merged_candidate_count": len(merged_candidates),
        "flat_fallback_candidate_count": len(flat_repairs),
        "returned_candidate_count": min(len(combined), max_candidates),
        "note": (
            "finite candidate generation is decomposed by repair-variable dependency components; "
            "flat fallback candidates are retained for completeness"
        ),
    }
    return combined[:max_candidates], skipped_static, summary


def hinted_candidate_edits(targets: list[BoundTarget], mutation_hint: dict | None) -> list[BoundEdit]:
    if not mutation_hint:
        return []
    template = mutation_hint.get("template")
    owner = mutation_hint.get("owner")
    label_kind = mutation_hint.get("label_kind")
    new_bound = mutation_hint.get("old_bound_value")
    mutated_bound = mutation_hint.get("new_bound")
    mutation_delta = mutation_hint.get("delta")
    original = mutation_hint.get("original", "")
    original_match = CONSTRAINT_RE.search(original)
    original_clock = original_match.group("clock") if original_match else (original.split()[0] if original.split() else None)
    if not isinstance(new_bound, int) and not isinstance(mutation_delta, int):
        return []

    edits: list[BoundEdit] = []
    for target in targets:
        if template and target.template_name != template:
            continue
        if owner and target.owner_name != owner:
            continue
        if label_kind and target.label_kind != label_kind:
            continue
        if original_clock and target.clock != original_clock:
            continue
        if isinstance(mutated_bound, int) and target.bound_value != mutated_bound:
            continue
        if not isinstance(new_bound, int) and isinstance(mutation_delta, int):
            edits.append(
                BoundEdit(
                    target=target,
                    new_bound=None,
                    delta=-mutation_delta,
                    reason="dataset mutation hint: revert changed clock-bound expression delta",
                    relation_score=1_000_000.0,
                )
            )
            continue
        edits.append(
            BoundEdit(
                target=target,
                new_bound=new_bound,
                delta=(new_bound - target.bound_value) if target.bound_value is not None else None,
                reason="dataset mutation hint: revert changed clock bound",
                relation_score=1_000_000.0,
            )
        )
    return edits


def template_environment(root: ET.Element, template_index: int) -> tuple[dict[str, int], set[str]]:
    global_decl = root.findtext("declaration") or ""
    template = root.findall("template")[template_index]
    local_decl = template.findtext("declaration") or ""
    mutable_variables = extract_assigned_variables(root)
    constants = {
        **extract_constants(global_decl, mutable_variables=mutable_variables),
        **extract_constants(local_decl, mutable_variables=mutable_variables),
    }
    clocks = extract_clocks(global_decl) | extract_clocks(local_decl)
    return constants, clocks


def constraints_in_label(text: str, constants: dict[str, int], clocks: set[str]) -> list[tuple[str, str, int]]:
    constraints: list[tuple[str, str, int]] = []
    for match in CONSTRAINT_RE.finditer(text or ""):
        clock = match.group("clock")
        if clock not in clocks:
            continue
        bound_text = match.group("bound").strip()
        if not is_supported_bound_expression(bound_text, clocks):
            continue
        value = bound_value(bound_text, constants)
        if value is None:
            continue
        constraints.append((clock, match.group("op"), value))
    return constraints


def static_admissible_edit(root: ET.Element, edit: BoundEdit) -> tuple[bool, str | None]:
    """Cheap syntactic admissibility filter.

    It rejects candidates that obviously mask behavior by making an outgoing
    transition from a location impossible, e.g. lowering an invariant ``x<=808``
    to ``x<=0`` while the same location has an outgoing guard ``x==808``.
    This is not a complete functional-equivalence check, but it is a useful
    practical guardrail before expensive verification.
    """

    target = edit.target
    if edit.new_bound is None:
        return True, None
    template = root.findall("template")[target.template_index]
    constants, clocks = template_environment(root, target.template_index)

    if target.owner_kind == "location" and target.label_kind == "invariant" and edit.operator in {"<=", "<", "=="}:
        location = template.findall("location")[target.owner_index]
        location_id = location.get("id")
        if location_id:
            for transition in template.findall("transition"):
                source = transition.find("source")
                if source is None or source.get("ref") != location_id:
                    continue
                for label in transition.findall("label"):
                    if label.get("kind") != "guard":
                        continue
                    for clock, op, value in constraints_in_label(label.text or "", constants, clocks):
                        if clock != edit.clock:
                            continue
                        if op in {">=", ">", "=="} and edit.new_bound < value:
                            return (
                                False,
                                f"would make outgoing guard {clock} {op} {value} unreachable from {target.owner_name}",
                            )

    if target.owner_kind == "transition" and target.label_kind == "guard" and edit.operator in {">=", ">", "=="}:
        transition = template.findall("transition")[target.owner_index]
        source = transition.find("source")
        source_ref = source.get("ref") if source is not None else None
        source_location = None
        if source_ref:
            for location in template.findall("location"):
                if location.get("id") == source_ref:
                    source_location = location
                    break
        if source_location is not None:
            for label in source_location.findall("label"):
                if label.get("kind") != "invariant":
                    continue
                for clock, op, value in constraints_in_label(label.text or "", constants, clocks):
                    if clock != edit.clock:
                        continue
                    if op in {"<=", "<", "=="} and edit.new_bound > value:
                        return (
                            False,
                            f"would exceed source invariant {clock} {op} {value} before guard {edit.new_expr}",
                        )

    return True, None


def _cleanup_assignment_text(text: str) -> str:
    text = re.sub(r"\s*,\s*", ", ", text.strip())
    text = re.sub(r"^(?:,|;)\s*", "", text)
    text = re.sub(r"\s*(?:,|;)$", "", text)
    text = re.sub(r"\s*(?:,|;)\s*(?:,|;)\s*", ", ", text)
    return text.strip()


def apply_edits(root: ET.Element, edits: list[RepairEdit]) -> ET.Element:
    root_copy = ET.fromstring(ET.tostring(root, encoding="utf-8"))
    bound_edits = [edit for edit in edits if isinstance(edit, BoundEdit)]
    reset_edits = [edit for edit in edits if isinstance(edit, ResetEdit)]
    edits_by_label: dict[tuple[int, str, int, str, int], list[BoundEdit]] = {}
    for edit in bound_edits:
        key = (
            edit.target.template_index,
            edit.target.owner_kind,
            edit.target.owner_index,
            edit.target.label_kind,
            edit.target.label_index,
        )
        edits_by_label.setdefault(key, []).append(edit)

    for key, label_edits in edits_by_label.items():
        template_index, owner_kind, owner_index, label_kind, label_index = key
        template = root_copy.findall("template")[template_index]
        if owner_kind == "location":
            owner = template.findall("location")[owner_index]
        else:
            owner = template.findall("transition")[owner_index]
        labels = [label for label in owner.findall("label") if label.get("kind") == label_kind]
        label = labels[label_index]
        text = label.text or ""
        for edit in sorted(label_edits, key=lambda item: item.target.start, reverse=True):
            target = edit.target
            text = text[: target.start] + edit.new_expr + text[target.end :]
        label.text = text

    for edit in reset_edits:
        target = edit.target
        template = root_copy.findall("template")[target.template_index]
        transition = template.findall("transition")[target.transition_index]
        assignment_labels = [
            label for label in transition.findall("label") if label.get("kind") == "assignment"
        ]
        if edit.action == "delete":
            if target.label_index is None or target.start is None or target.end is None:
                continue
            if target.label_index >= len(assignment_labels):
                continue
            label = assignment_labels[target.label_index]
            text = label.text or ""
            label.text = _cleanup_assignment_text(text[: target.start] + text[target.end :])
            if not label.text:
                transition.remove(label)
        elif edit.action == "add":
            new_reset = f"{target.clock} := 0"
            if target.label_index is not None and target.label_index < len(assignment_labels):
                label = assignment_labels[target.label_index]
                text = _cleanup_assignment_text(label.text or "")
                if not any(match.group("clock") == target.clock for match in RESET_RE.finditer(text)):
                    label.text = f"{text}, {new_reset}" if text else new_reset
            else:
                label = ET.SubElement(transition, "label", {"kind": "assignment"})
                label.text = new_reset
    return root_copy


def write_model(root: ET.Element, path: Path) -> None:
    ET.indent(root, space="    ")
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def verify_properties_individually(
    model_path: Path,
    properties: list[str],
    verifyta: Path,
    timeout: int,
) -> list[int]:
    violated: list[int] = []
    for index, formula in enumerate(properties, 1):
        result = verify_property(model_path, formula, verifyta_path=verifyta, timeout=timeout)
        if result.status == "not_satisfied":
            violated.append(index)
    return violated


def build_admissibility_config(config: RepairRunConfig, output_dir: Path) -> AdmissibilityConfig:
    return AdmissibilityConfig(
        tartar_root=config.admissibility_tartar_root,
        output_dir=output_dir,
        runner=config.admissibility_runner,
        timeout=config.admissibility_timeout,
        keep_transition_systems=True,
    )


def repair_model(
    model_path: Path,
    query_path: Path,
    output_dir: Path,
    config: RepairRunConfig,
    mutation_hint: dict | None = None,
) -> RepairRunResult:
    start = time.time()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "repair_report.json"
    repaired_model_path = output_dir / "repaired_model.xml"
    notes: list[str] = []
    config.use_symbolic_smt = True
    config.require_admissibility = True
    config.enable_operator_repairs = False
    config.enable_clock_repairs = False
    config.enable_reset_repairs = False

    properties = extract_properties(query_path)
    use_metadata_status = config.use_mutation_hints and mutation_hint and mutation_hint.get("violated_properties")
    if use_metadata_status:
        initial_status = "not_satisfied_metadata"
        violated_indices = [item["index"] for item in mutation_hint.get("violated_properties", []) if "index" in item]
        notes.append("initial violated properties were read from mutation metadata")
    else:
        initial = verify_query_file(model_path, query_path, verifyta_path=config.verifyta, timeout=config.timeout)
        initial_status = initial.status
        violated_indices = []

    if initial_status == "satisfied":
        shutil.copy2(model_path, repaired_model_path)
        result = RepairRunResult(
            status="already_satisfied",
            model=str(model_path),
            properties=str(query_path),
            repaired_model=str(repaired_model_path),
            initial_status=initial_status,
            final_status=initial_status,
            property_count=len(properties),
            violated_properties=[],
            target_count=0,
            candidate_count=0,
            tried_candidates=0,
            elapsed_sec=round(time.time() - start, 3),
            notes=["input model already satisfies the full property set"],
        )
        write_json(report_path, result.to_dict())
        return result

    if not violated_indices:
        violated_indices = verify_properties_individually(model_path, properties, config.verifyta, config.timeout)
    root = ET.parse(model_path).getroot()
    targets, constants, clocks = collect_targets(root)
    property_specs = [parse_property(index, formula, clocks) for index, formula in enumerate(properties, 1)]
    violated_specs = [prop for prop in property_specs if prop.index in violated_indices]
    analysis = analyze_search_space(targets, property_specs, violated_specs)
    strict_relations_report: PropertyRelationReport | None = None
    try:
        strict_relations = analyze_property_relations(properties, clocks, constants)
        strict_relations_report = strict_relations
        analysis["strict_property_relations"] = strict_relations.to_dict()
        if strict_relations.equivalent_groups:
            notes.append(f"strict property analysis found equivalent groups: {strict_relations.equivalent_groups}")
        if strict_relations.implications:
            notes.append(f"strict property analysis found {len(strict_relations.implications)} implication(s)")
        if strict_relations.conflicts:
            notes.append(f"strict property analysis found {len(strict_relations.conflicts)} conflict(s)")
        if strict_relations.unsupported:
            notes.append(
                "strict property analysis skipped unsupported formulas: "
                + ", ".join(f"P{index}" for index in sorted(strict_relations.unsupported))
            )
    except Exception as exc:
        analysis["strict_property_relations_error"] = str(exc)
        notes.append(f"strict property analysis failed: {exc}")
    if len(properties) > 1:
        try:
            reachable_relations = analyze_reachable_property_relations(
                model_path,
                properties,
                config.verifyta,
                config.timeout,
            )
            analysis["reachable_property_relations"] = reachable_relations
            if reachable_relations["implications"]:
                notes.append(
                    "reachable-state property analysis found "
                    f"{len(reachable_relations['implications'])} implication(s) on the current model"
                )
            if reachable_relations["conflicts"]:
                notes.append(
                    "reachable-state property analysis found "
                    f"{len(reachable_relations['conflicts'])} conflict(s) on the current model"
                )
            if reachable_relations["unsupported"]:
                notes.append(
                    "reachable-state property analysis skipped unsupported formulas: "
                    + ", ".join(f"P{index}" for index in sorted(reachable_relations["unsupported"]))
                )
        except Exception as exc:
            analysis["reachable_property_relations_error"] = str(exc)
            notes.append(f"reachable-state property analysis failed: {exc}")
    notes.append(
        "search-space analysis: "
        f"{analysis['repair_variable_count']} repair variables, "
        f"{analysis['dependency_component_count']} dependency component(s), "
        f"largest component size {analysis['largest_dependency_component']}"
    )

    tried = 0
    generated_candidate_count = 0
    final_status: str | None = None
    attempts: list[dict] = []
    blocked_exact: set[tuple[tuple[str, str, str, int | None, int | None], ...]] = set()
    attempted_exact: set[tuple[tuple[str, str, str, int | None, int | None], ...]] = set()
    refined_violated_indices = set(violated_indices)
    symbolic_trace_pool: dict[int, list[Path]] = {}
    symbolic_trace_signatures: dict[int, set[tuple[tuple[str, ...], ...]]] = {}
    symbolic_cache: dict[
        tuple[
            tuple[int, ...],
            tuple[str, ...],
            tuple[tuple[tuple[str, int | float], ...], ...],
            tuple[str, ...],
        ],
        list[CandidateRepair],
    ] = {}
    symbolic_blocked_assignments: list[dict[str, int | float]] = []
    symbolic_blocked_sites: set[str] = set()
    relation_note_seen: set[str] = set()

    def add_symbolic_traces(
        source_model_path: Path,
        property_indices: list[int],
        trace_dir: Path,
        note_prefix: str,
    ) -> bool:
        if not property_indices:
            return False
        trace_paths, trace_notes = collect_verifyta_traces(
            model_path=source_model_path,
            query_path=query_path,
            properties=properties,
            violated_indices=property_indices,
            verifyta_path=config.verifyta,
            output_dir=trace_dir,
            timeout=config.timeout,
            max_traces_per_property=config.symbolic_traces_per_property,
            known_signatures=symbolic_trace_signatures,
        )
        notes.extend(f"{note_prefix}: {item}" for item in trace_notes)
        for trace_path in trace_paths:
            match = re.search(r"property_(\d+)_trace", trace_path.name)
            if not match:
                continue
            symbolic_trace_pool.setdefault(int(match.group(1)), []).append(trace_path)
        return bool(trace_paths)

    with tempfile.TemporaryDirectory(prefix="mpta_repair_") as tmp_name:
        tmp_dir = Path(tmp_name)
        for round_index in range(1, config.max_refinement_rounds + 1):
            current_violated_specs = [
                prop for prop in property_specs if prop.index in refined_violated_indices
            ]
            symbolic_repairs: list[CandidateRepair] = []
            static_filter_blocked_symbolic = False
            symbolic_indices, relation_notes = relation_pruned_symbolic_indices(
                refined_violated_indices,
                strict_relations_report,
            )
            for relation_note in relation_notes:
                if relation_note not in relation_note_seen:
                    relation_note_seen.add(relation_note)
                    notes.append(f"round {round_index}: {relation_note}")
            symbolic_property_key = tuple(symbolic_indices)
            if symbolic_property_key:
                missing_trace_indices = [
                    index for index in symbolic_property_key if not symbolic_trace_pool.get(index)
                ]
                if missing_trace_indices:
                    add_symbolic_traces(
                        model_path,
                        missing_trace_indices,
                        output_dir / "symbolic_traces" / f"round_{round_index}" / "initial",
                        f"round {round_index}",
                    )
                trace_paths = [
                    path
                    for index in symbolic_property_key
                    for path in symbolic_trace_pool.get(index, [])
                ]
                symbolic_key = (
                    symbolic_property_key,
                    tuple(str(path) for path in trace_paths),
                    tuple(tuple(sorted(assignment.items())) for assignment in symbolic_blocked_assignments),
                    tuple(sorted(symbolic_blocked_sites)),
                )
                if trace_paths and symbolic_key not in symbolic_cache:
                    symbolic_result = solve_symbolic_repair(
                        trace_paths=trace_paths,
                        properties_by_index={index: formula for index, formula in enumerate(properties, 1)},
                        max_bound_delta=config.symbolic_max_bound_delta,
                        model_path=model_path,
                        enable_operator_variation=False,
                        enable_clock_reference_variation=False,
                        use_dbm_constraints=config.symbolic_use_dbm,
                        blocked_assignments=symbolic_blocked_assignments,
                        blocked_sites=symbolic_blocked_sites,
                        qe_timeout_ms=max(1000, int(config.qe_timeout * 1000)),
                    )
                    analysis.setdefault("symbolic_smt_rounds", []).append(symbolic_result.to_dict())
                    if symbolic_result.dag:
                        saved_nodes = symbolic_result.dag.get("saved_universal_nodes", 0)
                        saved_edges = symbolic_result.dag.get("saved_universal_edges", 0)
                        if saved_nodes or saved_edges:
                            notes.append(
                                f"round {round_index}: Path-DAG shared encoding saved "
                                f"{saved_nodes} universal node(s) and {saved_edges} edge block(s)"
                            )
                    path_relations = symbolic_result.path_relations or {}
                    if path_relations.get("common_subpaths"):
                        notes.append(
                            f"round {round_index}: mined {len(path_relations['common_subpaths'])} "
                            "common subpath pattern(s)"
                        )
                    if path_relations.get("dominance_pairs"):
                        notes.append(
                            f"round {round_index}: SMT path dominance found "
                            f"{len(path_relations['dominance_pairs'])} implication pair(s)"
                        )
                    if path_relations.get("clusters"):
                        notes.append(
                            f"round {round_index}: path clustering produced "
                            f"{len(path_relations['clusters'])} representative cluster(s)"
                        )
                    repairs, mapping_notes = symbolic_changes_to_candidate_repairs(
                        symbolic_result.changes,
                        targets,
                        property_specs,
                        current_violated_specs,
                    )
                    notes.extend(f"round {round_index}: {item}" for item in mapping_notes)
                    filtered_repairs: list[CandidateRepair] = []
                    for repair in repairs:
                        if len(repair.edits) > config.max_changes:
                            notes.append(
                                f"round {round_index}: symbolic repair needs {len(repair.edits)} change(s), "
                                f"above --max-changes={config.max_changes}"
                            )
                            continue
                        ok, reason = combined_static_admissible(root, repair.edits)
                        if not ok:
                            notes.append(f"round {round_index}: symbolic repair failed static filter: {reason}")
                            if repair.symbolic_assignment is not None:
                                symbolic_blocked_assignments.append(repair.symbolic_assignment)
                                blocked_site_keys = sorted(repair.symbolic_assignment)
                                symbolic_blocked_sites.update(blocked_site_keys)
                                static_filter_blocked_symbolic = True
                                notes.append(
                                    f"round {round_index}: blocked statically invalid symbolic repair assignment"
                                    f" and site(s): {', '.join(blocked_site_keys)}"
                                )
                            continue
                        filtered_repairs.append(repair)
                    symbolic_cache[symbolic_key] = filtered_repairs
                    if symbolic_result.status == "repaired":
                        notes.append(
                            f"round {round_index}: Z3 TDT repair produced "
                            f"{len(symbolic_result.changes)} bound change(s)"
                        )
                    else:
                        notes.append(f"round {round_index}: Z3 TDT repair status is {symbolic_result.status}")
                symbolic_repairs = symbolic_cache.get(symbolic_key, [])
            active_trace_paths = [
                path
                for index in symbolic_property_key
                for path in symbolic_trace_pool.get(index, [])
            ]
            tdt_site_coverage = trace_site_coverage(active_trace_paths)
            if tdt_site_coverage:
                analysis.setdefault("trace_site_coverage_rounds", []).append(
                    {
                        "round": round_index,
                        "sites": [
                            {
                                "template": key[0],
                                "owner_kind": key[1],
                                "owner": key[2],
                                "label_kind": key[3],
                                "clock": key[4],
                                "coverage": value,
                            }
                            for key, value in sorted(
                                tdt_site_coverage.items(),
                                key=lambda item: (-item[1], item[0]),
                            )[:20]
                        ],
                    }
                )

            skipped_static = 0
            candidate_repairs = symbolic_repairs[: config.max_candidates]
            candidate_repairs = [
                candidate
                for candidate in candidate_repairs
                if candidate.key not in blocked_exact and candidate.key not in attempted_exact
            ]
            generated_candidate_count += len(candidate_repairs)
            if skipped_static:
                notes.append(
                    f"round {round_index}: static admissibility/WF filters skipped "
                    f"{skipped_static} candidate assignment(s)"
                )
            notes.append(
                f"round {round_index}: generated {len(candidate_repairs)} symbolic TDT/Z3 repair assignment(s) "
                f"with up to {config.max_changes} changed bound(s); finite candidate search is disabled"
            )
            if not candidate_repairs:
                if static_filter_blocked_symbolic:
                    continue
                break

            discovered_new_refinement = False
            for candidate in candidate_repairs:
                if tried >= config.max_candidates:
                    break
                tried += 1
                attempted_exact.add(candidate.key)
                candidate_root = apply_edits(root, list(candidate.edits))
                candidate_path = tmp_dir / f"candidate_{tried:04d}.xml"
                write_model(candidate_root, candidate_path)
                verification = verify_query_file(
                    candidate_path,
                    query_path,
                    verifyta_path=config.verifyta,
                    timeout=config.timeout,
                )
                final_status = verification.status
                attempt = {
                    "index": tried,
                    "round": round_index,
                    "candidate": candidate.to_dict(),
                    "verification_status": verification.status,
                    "verification_duration_sec": verification.duration_sec,
                    "violated_properties": [],
                    "liveness": None,
                    "liveness_elapsed_sec": None,
                    "admissibility_status": None,
                    "admissibility_elapsed_sec": None,
                    "blocked": False,
                }
                if verification.status == "satisfied":
                    if config.require_liveness_checks:
                        liveness_start = time.time()
                        liveness = run_liveness_checks(candidate_path, config.verifyta, config.timeout)
                        attempt["liveness"] = liveness.to_dict()
                        attempt["liveness_elapsed_sec"] = round(time.time() - liveness_start, 3)
                        if not liveness.ok:
                            blocked_exact.add(candidate.key)
                            attempt["blocked"] = True
                            notes.append(
                                f"candidate {tried} satisfied all properties but failed liveness checks: "
                                f"timelock={liveness.timelock_status}, zeno={liveness.zeno_status}"
                            )
                            attempts.append(attempt)
                            continue
                    admissibility_status: str | None = None
                    admissibility_report: str | None = None
                    admissibility_counterexample: list[str] = []
                    accepted_candidate_path = candidate_path
                    if config.require_admissibility:
                        admissibility_candidate_dir = output_dir / "admissibility_candidates"
                        admissibility_candidate_dir.mkdir(exist_ok=True)
                        accepted_candidate_path = admissibility_candidate_dir / f"candidate_{tried:04d}.xml"
                        shutil.copy2(candidate_path, accepted_candidate_path)
                        admissibility_root = config.admissibility_output_dir or (output_dir / "admissibility")
                        admissibility_config = build_admissibility_config(
                            config,
                            admissibility_root / f"candidate_{tried:04d}",
                        )
                        admissibility = check_admissibility(model_path, accepted_candidate_path, admissibility_config)
                        admissibility_status = admissibility.status
                        admissibility_report = str(Path(admissibility.output_dir) / "admissibility_report.json")
                        admissibility_counterexample = admissibility.counterexample
                        attempt["admissibility_status"] = admissibility_status
                        attempt["admissibility_report"] = admissibility_report
                        attempt["admissibility_elapsed_sec"] = admissibility.elapsed_sec
                        attempt["admissibility_counterexample"] = admissibility_counterexample
                        if admissibility.status != "admissible":
                            blocked_exact.add(candidate.key)
                            if candidate.symbolic_assignment is not None:
                                symbolic_blocked_assignments.append(candidate.symbolic_assignment)
                                discovered_new_refinement = True
                            attempt["blocked"] = True
                            notes.append(
                                f"candidate {tried} satisfied all properties but failed admissibility: "
                                f"{admissibility.status}; blocked exact symbolic repair assignment"
                            )
                            if admissibility.counterexample:
                                notes.append(
                                    "admissibility separating trace: "
                                    + " -> ".join(admissibility.counterexample)
                                )
                            attempts.append(attempt)
                            if admissibility.status == "environment_missing":
                                result = RepairRunResult(
                                    status="admissibility_unavailable",
                                    model=str(model_path),
                                    properties=str(query_path),
                                    repaired_model=None,
                                    initial_status=initial_status,
                                    final_status=verification.status,
                                    property_count=len(properties),
                                    violated_properties=sorted(refined_violated_indices),
                                    target_count=len(targets),
                                    candidate_count=generated_candidate_count,
                                    tried_candidates=tried,
                                    elapsed_sec=round(time.time() - start, 3),
                                    edits=[edit.to_dict() for edit in candidate.edits],
                                    notes=notes,
                                    analysis=analysis,
                                    attempts=attempts,
                                    admissibility_status=admissibility_status,
                                    admissibility_report=admissibility_report,
                                    admissibility_counterexample=admissibility_counterexample,
                                )
                                write_json(report_path, result.to_dict())
                                return result
                            break
                    attempts.append(attempt)
                    shutil.copy2(accepted_candidate_path, repaired_model_path)
                    result = RepairRunResult(
                        status="repaired",
                        model=str(model_path),
                        properties=str(query_path),
                        repaired_model=str(repaired_model_path),
                        initial_status=initial_status,
                        final_status=verification.status,
                        property_count=len(properties),
                        violated_properties=sorted(refined_violated_indices),
                        target_count=len(targets),
                        candidate_count=generated_candidate_count,
                        tried_candidates=tried,
                        elapsed_sec=round(time.time() - start, 3),
                        edits=[edit.to_dict() for edit in candidate.edits],
                        notes=notes,
                        analysis=analysis,
                        attempts=attempts,
                        admissibility_status=admissibility_status,
                        admissibility_report=admissibility_report,
                        admissibility_counterexample=admissibility_counterexample,
                    )
                    write_json(report_path, result.to_dict())
                    return result

                if verification.status == "not_satisfied":
                    if len(properties) == 1:
                        failed_properties = [1]
                    else:
                        failed_properties = verify_properties_individually(
                            candidate_path,
                            properties,
                            config.verifyta,
                            config.timeout,
                        )
                    attempt["violated_properties"] = failed_properties
                    newly_violated = set(failed_properties) - refined_violated_indices
                    if newly_violated:
                        refined_violated_indices.update(newly_violated)
                        discovered_new_refinement = True
                        notes.append(
                            f"candidate {tried} exposed additional violated propert"
                            f"{'y' if len(newly_violated) == 1 else 'ies'} "
                            f"{sorted(newly_violated)}; refining candidate ranking"
                        )
                    failed_symbolic_properties, relation_notes = relation_pruned_symbolic_indices(
                        failed_properties,
                        strict_relations_report,
                    )
                    for relation_note in relation_notes:
                        if relation_note not in relation_note_seen:
                            relation_note_seen.add(relation_note)
                            notes.append(f"candidate {tried}: {relation_note}")
                    new_tdt = add_symbolic_traces(
                        candidate_path,
                        failed_symbolic_properties,
                        output_dir / "symbolic_traces" / f"round_{round_index}" / f"candidate_{tried:04d}",
                        f"candidate {tried}",
                    )
                    if new_tdt:
                        discovered_new_refinement = True
                        notes.append(
                            f"candidate {tried} added new TDT signature(s); refining symbolic repair constraints"
                        )
                    if candidate.symbolic_assignment is not None:
                        symbolic_blocked_assignments.append(candidate.symbolic_assignment)
                        discovered_new_refinement = True
                        blocked_exact.add(candidate.key)
                        attempt["blocked"] = True
                        notes.append(
                            f"candidate {tried} failed full-property verification; blocked exact symbolic repair assignment"
                        )
                attempts.append(attempt)
                if config.keep_failed_candidates:
                    failed_dir = output_dir / "failed_candidates"
                    failed_dir.mkdir(exist_ok=True)
                    shutil.copy2(candidate_path, failed_dir / candidate_path.name)
                if discovered_new_refinement:
                    break
            if tried >= config.max_candidates or not discovered_new_refinement:
                break

    result = RepairRunResult(
        status="no_repair_found",
        model=str(model_path),
        properties=str(query_path),
        repaired_model=None,
        initial_status=initial_status,
        final_status=final_status,
        property_count=len(properties),
        violated_properties=sorted(refined_violated_indices),
        target_count=len(targets),
        candidate_count=generated_candidate_count,
        tried_candidates=tried,
        elapsed_sec=round(time.time() - start, 3),
        notes=notes
        + [
            "no candidate satisfied both all properties and admissibility"
            if config.require_admissibility
            else "no repair assignment in the ranked candidate set satisfied all properties"
        ],
        analysis=analysis,
        attempts=attempts,
    )
    write_json(report_path, result.to_dict())
    return result


def expected_reverted(result: RepairRunResult, mutation: dict | None) -> bool | None:
    if not mutation or not result.edits:
        return None
    expected_old = mutation.get("old_bound_value")
    template = mutation.get("template")
    owner = mutation.get("owner")
    label_kind = mutation.get("label_kind")
    original = mutation.get("original", "")
    original_match = CONSTRAINT_RE.search(original)
    original_clock = original_match.group("clock") if original_match else (original.split()[0] if original.split() else None)
    for edit in result.edits:
        same_place = (
            edit.get("template") == template
            and edit.get("owner") == owner
            and edit.get("label_kind") == label_kind
        )
        same_bound = edit.get("new_bound") == expected_old
        same_clock = original_clock == edit.get("clock") if original_clock else True
        if same_place and same_bound and same_clock:
            return True
    return False


def discover_mutants(dataset_root: Path) -> list[Path]:
    return sorted(dataset_root.glob("*/*/bound_mod_*/mutation.json"))


def case_output_dir(output_root: Path, mutation_json: Path, dataset_root: Path) -> Path:
    return output_root / mutation_json.parent.relative_to(dataset_root)


def run_dataset(
    dataset_root: Path,
    output_root: Path,
    config: RepairRunConfig,
    limit: int = 0,
    families: set[str] | None = None,
) -> dict:
    start = time.time()
    output_root.mkdir(parents=True, exist_ok=True)
    mutation_files = discover_mutants(dataset_root)
    if families:
        mutation_files = [
            path for path in mutation_files if path.relative_to(dataset_root).parts[0] in families
        ]
    if limit:
        mutation_files = mutation_files[:limit]

    rows: list[dict] = []
    for index, mutation_path in enumerate(mutation_files, 1):
        mutation = json.loads(read_text(mutation_path))
        mutant_dir = mutation_path.parent
        model_path = mutant_dir / "model.xml"
        query_path = mutant_dir / "properties.q"
        out_dir = case_output_dir(output_root, mutation_path, dataset_root)
        print(f"[{index}/{len(mutation_files)}] repairing {mutant_dir.relative_to(dataset_root)}", flush=True)
        case_config = config
        if config.admissibility_output_dir is not None:
            case_config = replace(
                config,
                admissibility_output_dir=config.admissibility_output_dir / out_dir.relative_to(output_root),
            )
        result = repair_model(model_path, query_path, out_dir, case_config, mutation if config.use_mutation_hints else None)
        symbolic_rounds = result.analysis.get("symbolic_smt_rounds", []) if isinstance(result.analysis, dict) else []
        symbolic_elapsed = round(
            sum(float(round_item.get("elapsed_sec", 0.0)) for round_item in symbolic_rounds),
            3,
        )
        verification_elapsed = round(
            sum(float(attempt.get("verification_duration_sec") or 0.0) for attempt in result.attempts),
            3,
        )
        admissibility_elapsed = round(
            sum(float(attempt.get("admissibility_elapsed_sec") or 0.0) for attempt in result.attempts),
            3,
        )
        liveness_elapsed = round(
            sum(float(attempt.get("liveness_elapsed_sec") or 0.0) for attempt in result.attempts),
            3,
        )
        attempt_statuses = [
            {
                "index": attempt.get("index"),
                "round": attempt.get("round"),
                "verification_status": attempt.get("verification_status"),
                "verification_duration_sec": attempt.get("verification_duration_sec"),
                "violated_property_count": len(attempt.get("violated_properties") or []),
                "violated_properties": attempt.get("violated_properties") or [],
                "liveness_elapsed_sec": attempt.get("liveness_elapsed_sec"),
                "liveness_ok": attempt.get("liveness", {}).get("ok") if attempt.get("liveness") else None,
                "admissibility_status": attempt.get("admissibility_status"),
                "admissibility_elapsed_sec": attempt.get("admissibility_elapsed_sec"),
                "blocked": attempt.get("blocked", False),
            }
            for attempt in result.attempts
        ]
        row = {
            "family": mutation_path.relative_to(dataset_root).parts[0],
            "version": mutation_path.relative_to(dataset_root).parts[1],
            "mutant": mutation["id"],
            "mutation_description": mutation.get("description", ""),
            "violated_property_indices": [item["index"] for item in mutation.get("violated_properties", [])],
            "initial_violated_property_count": len(mutation.get("violated_properties", [])),
            "refined_violated_property_indices": result.violated_properties,
            "refined_violated_property_count": len(result.violated_properties),
            "status": result.status,
            "initial_status": result.initial_status,
            "final_status": result.final_status,
            "tried_candidates": result.tried_candidates,
            "candidate_count": result.candidate_count,
            "elapsed_sec": result.elapsed_sec,
            "symbolic_smt_round_count": len(symbolic_rounds),
            "symbolic_smt_elapsed_sec": symbolic_elapsed,
            "candidate_verification_elapsed_sec": verification_elapsed,
            "liveness_elapsed_sec": liveness_elapsed,
            "admissibility_elapsed_sec": admissibility_elapsed,
            "attempt_statuses": attempt_statuses,
            "edits": result.edits,
            "expected_reverted": expected_reverted(result, mutation),
            "report": str(out_dir / "repair_report.json"),
            "repaired_model": result.repaired_model,
            "admissibility_status": result.admissibility_status,
            "admissibility_report": result.admissibility_report,
        }
        rows.append(row)

    summary = {
        "dataset_root": str(dataset_root),
        "output_root": str(output_root),
        "verifyta": str(config.verifyta),
        "timeout": config.timeout,
        "max_candidates": config.max_candidates,
        "max_changes": config.max_changes,
        "max_refinement_rounds": config.max_refinement_rounds,
        "use_mutation_hints": config.use_mutation_hints,
        "use_symbolic_smt": config.use_symbolic_smt,
        "symbolic_max_bound_delta": config.symbolic_max_bound_delta,
        "symbolic_traces_per_property": config.symbolic_traces_per_property,
        "symbolic_use_dbm": config.symbolic_use_dbm,
        "enable_operator_repairs": config.enable_operator_repairs,
        "enable_clock_repairs": config.enable_clock_repairs,
        "enable_reset_repairs": config.enable_reset_repairs,
        "require_liveness_checks": config.require_liveness_checks,
        "require_admissibility": config.require_admissibility,
        "admissibility_runner": config.admissibility_runner,
        "admissibility_timeout": config.admissibility_timeout,
        "mutant_count": len(rows),
        "repaired_count": sum(1 for row in rows if row["status"] in {"repaired", "already_satisfied"}),
        "no_repair_count": sum(1 for row in rows if row["status"] == "no_repair_found"),
        "expected_reverted_count": sum(1 for row in rows if row["expected_reverted"] is True),
        "elapsed_sec": round(time.time() - start, 3),
        "results": rows,
    }
    write_json(output_root / "summary.json", summary)
    write_text(output_root / "summary.md", render_dataset_summary(summary))
    return summary


def render_dataset_summary(summary: dict) -> str:
    rows = summary["results"]
    lines = [
        "# Multi-Property Clock-Bound Repair Experiment",
        "",
        "This report was generated by `scripts/repair_multi_property.py dataset`.",
        "",
        "## Configuration",
        "",
        f"- Dataset root: `{summary['dataset_root']}`",
        f"- Output root: `{summary['output_root']}`",
        f"- verifyta: `{summary['verifyta']}`",
        f"- Timeout per verification: {summary['timeout']} s",
        f"- Max symbolic repair attempts per mutant: {summary['max_candidates']}",
        f"- Max changed bounds per candidate: {summary.get('max_changes', 1)}",
        f"- Max refinement rounds: {summary.get('max_refinement_rounds', 1)}",
        f"- Mutation localization hints: {summary.get('use_mutation_hints', False)}",
        f"- TDT/Z3 symbolic repair: mandatory",
        f"- Symbolic max bound delta: {summary.get('symbolic_max_bound_delta') if summary.get('symbolic_max_bound_delta') is not None else 'unbounded'}",
        f"- Symbolic traces per property: {summary.get('symbolic_traces_per_property') if summary.get('symbolic_traces_per_property') is not None else 'all available search orders'}",
        f"- Symbolic DBM trace constraints: {summary.get('symbolic_use_dbm', False)}",
        f"- Operator repair candidates: disabled",
        f"- Clock-reference repair candidates: disabled",
        f"- Reset repair candidates: disabled",
        f"- Timelock/zenoness checks required: {summary.get('require_liveness_checks', False)}",
        f"- TARTAR-style admissibility required: {summary.get('require_admissibility', True)}",
        f"- Admissibility runner: `{summary.get('admissibility_runner', 'auto')}`",
        "",
        "## Overall Result",
        "",
        f"- Mutants: {summary['mutant_count']}",
        f"- Repaired or already satisfied: {summary['repaired_count']}",
        f"- No repair found: {summary['no_repair_count']}",
        f"- Exact mutation reverts: {summary['expected_reverted_count']}",
        f"- Total elapsed time: {summary['elapsed_sec']} s",
        "",
        "## Result By Family",
        "",
        "| Family | Mutants | Repaired | No repair | Exact reverts | Avg tried candidates |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    families = sorted({row["family"] for row in rows})
    for family in families:
        family_rows = [row for row in rows if row["family"] == family]
        repaired = sum(1 for row in family_rows if row["status"] in {"repaired", "already_satisfied"})
        failed = sum(1 for row in family_rows if row["status"] == "no_repair_found")
        exact = sum(1 for row in family_rows if row["expected_reverted"] is True)
        avg_tried = sum(row["tried_candidates"] for row in family_rows) / len(family_rows)
        lines.append(
            f"| {family} | {len(family_rows)} | {repaired} | {failed} | {exact} | {avg_tried:.1f} |"
        )

    lines.extend(
        [
            "",
        "## Per-Mutant Details",
        "",
        "| Family | Version | Mutant | Status | Init violated | Refined violated | Tried | Total s | SMT s | Verify s | Live s | Admiss s | Admissibility | Exact revert | Repair edit |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
        ]
    )
    for row in rows:
        if row["edits"]:
            edit_parts = (
                f"{edit['template']}.{edit['owner']} {edit['label_kind']} "
                f"`{edit['old_expr']}` -> `{edit['new_expr']}`"
                for edit in row["edits"]
            )
            edit_text = "<br>".join(edit_parts)
        else:
            edit_text = ""
        lines.append(
            f"| {row['family']} | {row['version']} | {row['mutant']} | {row['status']} | "
            f"{row.get('initial_violated_property_count', len(row.get('violated_property_indices', [])))} | "
            f"{row.get('refined_violated_property_count', len(row.get('refined_violated_property_indices', [])))} | "
            f"{row['tried_candidates']} | {row['elapsed_sec']} | "
            f"{row.get('symbolic_smt_elapsed_sec', 0.0)} | "
            f"{row.get('candidate_verification_elapsed_sec', 0.0)} | "
            f"{row.get('liveness_elapsed_sec', 0.0)} | "
            f"{row.get('admissibility_elapsed_sec', 0.0)} | "
            f"{row.get('admissibility_status') or ''} | "
            f"{row['expected_reverted']} | {edit_text} |"
        )
    return "\n".join(lines) + "\n"


def comparison_variant_name(use_hints: bool, use_symbolic: bool, require_admissibility: bool) -> str:
    return "_".join(
        [
            "hint" if use_hints else "no_hint",
            "symbolic",
            "admissibility",
        ]
    )


def run_comparison_matrix(
    dataset_root: Path,
    output_root: Path,
    base_config: RepairRunConfig,
    limit: int = 0,
    families: set[str] | None = None,
) -> dict:
    start = time.time()
    output_root.mkdir(parents=True, exist_ok=True)
    variants = []
    for use_hints in [False, True]:
        variant_name = comparison_variant_name(use_hints, True, True)
        variant_config = replace(
            base_config,
            use_mutation_hints=use_hints,
            use_symbolic_smt=True,
            require_admissibility=True,
            admissibility_output_dir=(
                base_config.admissibility_output_dir / variant_name
                if base_config.admissibility_output_dir is not None
                else None
            ),
        )
        print(f"[comparison] running {variant_name}", flush=True)
        summary = run_dataset(
            dataset_root=dataset_root,
            output_root=output_root / variant_name,
            config=variant_config,
            limit=limit,
            families=families,
        )
        variants.append(
            {
                "variant": variant_name,
                "use_mutation_hints": use_hints,
                "use_symbolic_smt": True,
                "require_admissibility": True,
                "summary_path": str(output_root / variant_name / "summary.json"),
                "mutant_count": summary["mutant_count"],
                "repaired_count": summary["repaired_count"],
                "no_repair_count": summary["no_repair_count"],
                "expected_reverted_count": summary["expected_reverted_count"],
                "admissibility_unavailable_count": sum(
                    1 for row in summary["results"] if row["status"] == "admissibility_unavailable"
                ),
                "avg_tried_candidates": (
                    round(
                        sum(row["tried_candidates"] for row in summary["results"])
                        / len(summary["results"]),
                        2,
                    )
                    if summary["results"]
                    else 0.0
                ),
                "elapsed_sec": summary["elapsed_sec"],
            }
        )
    comparison = {
        "dataset_root": str(dataset_root),
        "output_root": str(output_root),
        "verifyta": str(base_config.verifyta),
        "timeout": base_config.timeout,
        "max_candidates": base_config.max_candidates,
        "max_changes": base_config.max_changes,
        "max_refinement_rounds": base_config.max_refinement_rounds,
        "limit": limit,
        "families": sorted(families) if families else [],
        "elapsed_sec": round(time.time() - start, 3),
        "variants": variants,
    }
    write_json(output_root / "comparison_summary.json", comparison)
    write_text(output_root / "comparison_summary.md", render_comparison_summary(comparison))
    return comparison


def render_comparison_summary(comparison: dict) -> str:
    lines = [
        "# Multi-Property Repair Comparison Matrix",
        "",
        "This report compares blind repair with oracle mutation hints under the symbolic TDT/Z3 repair method with mandatory admissibility.",
        "",
        "## Configuration",
        "",
        f"- Dataset root: `{comparison['dataset_root']}`",
        f"- Output root: `{comparison['output_root']}`",
        f"- verifyta: `{comparison['verifyta']}`",
        f"- Timeout per verification: {comparison['timeout']} s",
        f"- Max candidates per mutant: {comparison['max_candidates']}",
        f"- Max changed bounds per candidate: {comparison['max_changes']}",
        f"- Max refinement rounds: {comparison['max_refinement_rounds']}",
        f"- Limit: {comparison.get('limit', 0)}",
        f"- Families: `{', '.join(comparison.get('families') or []) or 'all'}`",
        f"- Total elapsed time: {comparison['elapsed_sec']} s",
        "",
        "## Variants",
        "",
        "| Variant | Hints | Symbolic TDT | Admissibility | Mutants | Repaired | No repair | Admissibility unavailable | Exact reverts | Avg tried | Time |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in comparison["variants"]:
        lines.append(
            f"| {row['variant']} | {row['use_mutation_hints']} | {row['use_symbolic_smt']} | "
            f"{row['require_admissibility']} | {row['mutant_count']} | {row['repaired_count']} | "
            f"{row['no_repair_count']} | {row['admissibility_unavailable_count']} | "
            f"{row['expected_reverted_count']} | {row['avg_tried_candidates']:.2f} | {row['elapsed_sec']} s |"
        )
    return "\n".join(lines) + "\n"


def copy_summary_to_doc(summary_md: Path, doc_path: Path | None) -> None:
    if doc_path is None:
        return
    text = read_text(summary_md)
    write_text(doc_path, text)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Repair UPPAAL clock-bound mutants against multiple properties.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    repair = subparsers.add_parser("repair", help="Repair one model/property pair.")
    repair.add_argument("--model", type=Path, required=True)
    repair.add_argument("--properties", type=Path, required=True)
    repair.add_argument("--output-dir", type=Path, required=True)
    repair.add_argument("--verifyta", type=Path, default=DEFAULT_VERIFYTA)
    repair.add_argument("--timeout", type=int, default=60)
    repair.add_argument("--qe-timeout", type=int, default=500, help="QE timeout in seconds for symbolic SMT.")
    repair.add_argument("--max-candidates", type=int, default=300)
    repair.add_argument("--max-changes", type=int, default=4)
    repair.add_argument("--max-refinement-rounds", type=int, default=3)
    repair.add_argument("--keep-failed-candidates", action="store_true")
    repair.add_argument("--mutation-json", type=Path, help="Optional mutation metadata used as a localization hint.")
    repair.add_argument("--use-mutation-hints", action="store_true")
    repair.add_argument("--symbolic-use-dbm", action="store_true", help="Also encode UPPAAL XML trace DBM zone constraints in symbolic repair.")
    repair.add_argument("--require-liveness-checks", action="store_true", help="Require A[] not deadlock and a structural zenoness-risk screen for accepted repairs.")
    repair.add_argument("--tartar-root", type=Path, default=Path("TarTar-master"))
    repair.add_argument("--admissibility-runner", choices=["auto", "native", "wsl"], default="auto")
    repair.add_argument("--admissibility-timeout", type=int, default=3600)
    repair.add_argument("--admissibility-output-dir", type=Path)

    dataset = subparsers.add_parser("dataset", help="Repair all mutants in a dataset.")
    dataset.add_argument("--dataset-root", type=Path, default=Path("models/bound_modified_error_dataset"))
    dataset.add_argument("--output-root", type=Path, default=Path("experiments/multi_property_repair"))
    dataset.add_argument("--verifyta", type=Path, default=DEFAULT_VERIFYTA)
    dataset.add_argument("--timeout", type=int, default=60)
    dataset.add_argument("--qe-timeout", type=int, default=500, help="QE timeout in seconds for symbolic SMT.")
    dataset.add_argument("--max-candidates", type=int, default=300)
    dataset.add_argument("--max-changes", type=int, default=4)
    dataset.add_argument("--max-refinement-rounds", type=int, default=3)
    dataset.add_argument("--limit", type=int, default=0)
    dataset.add_argument("--families", help="Comma-separated family names to include.")
    dataset.add_argument("--doc-output", type=Path, help="Optional extra Markdown copy of the dataset summary.")
    dataset.add_argument("--symbolic-use-dbm", action="store_true", help="Also encode UPPAAL XML trace DBM zone constraints in symbolic repair.")
    dataset.add_argument("--require-liveness-checks", action="store_true", help="Require A[] not deadlock and a structural zenoness-risk screen for accepted repairs.")
    dataset.add_argument("--tartar-root", type=Path, default=Path("TarTar-master"))
    dataset.add_argument("--admissibility-runner", choices=["auto", "native", "wsl"], default="auto")
    dataset.add_argument("--admissibility-timeout", type=int, default=3600)
    dataset.add_argument("--admissibility-output-dir", type=Path)
    dataset.add_argument(
        "--use-mutation-hints",
        action="store_true",
        help="Use dataset mutation metadata as an oracle localization baseline.",
    )
    dataset.add_argument(
        "--no-mutation-hints",
        action="store_true",
        help="Deprecated compatibility flag; blind candidate search is now the default.",
    )
    comparison = subparsers.add_parser("comparison", help="Run a no-hint/hint comparison with symbolic repair and admissibility enabled.")
    comparison.add_argument("--dataset-root", type=Path, default=Path("models/bound_modified_error_dataset"))
    comparison.add_argument("--output-root", type=Path, default=Path("experiments/multi_property_repair_comparison"))
    comparison.add_argument("--verifyta", type=Path, default=DEFAULT_VERIFYTA)
    comparison.add_argument("--timeout", type=int, default=60)
    comparison.add_argument("--qe-timeout", type=int, default=500, help="QE timeout in seconds for symbolic SMT.")
    comparison.add_argument("--max-candidates", type=int, default=300)
    comparison.add_argument("--max-changes", type=int, default=4)
    comparison.add_argument("--max-refinement-rounds", type=int, default=3)
    comparison.add_argument("--limit", type=int, default=0)
    comparison.add_argument("--families", help="Comma-separated family names to include.")
    comparison.add_argument("--doc-output", type=Path, help="Optional extra Markdown copy of the comparison summary.")
    comparison.add_argument("--symbolic-use-dbm", action="store_true", help="Also encode UPPAAL XML trace DBM zone constraints in symbolic variants.")
    comparison.add_argument("--require-liveness-checks", action="store_true", help="Require A[] not deadlock and a structural zenoness-risk screen for accepted repairs.")
    comparison.add_argument("--tartar-root", type=Path, default=Path("TarTar-master"))
    comparison.add_argument("--admissibility-runner", choices=["auto", "native", "wsl"], default="auto")
    comparison.add_argument("--admissibility-timeout", type=int, default=3600)
    comparison.add_argument("--admissibility-output-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if not args.verifyta.exists():
        raise SystemExit(f"verifyta not found: {args.verifyta}")

    config = RepairRunConfig(
        verifyta=args.verifyta,
        timeout=args.timeout,
        qe_timeout=getattr(args, "qe_timeout", 500),
        max_candidates=args.max_candidates,
        max_changes=args.max_changes,
        max_refinement_rounds=args.max_refinement_rounds,
        keep_failed_candidates=getattr(args, "keep_failed_candidates", False),
        use_mutation_hints=getattr(args, "use_mutation_hints", False),
        use_symbolic_smt=True,
        symbolic_max_bound_delta=getattr(args, "symbolic_max_bound_delta", None),
        symbolic_traces_per_property=getattr(args, "symbolic_traces_per_property", 1),
        symbolic_use_dbm=getattr(args, "symbolic_use_dbm", False),
        enable_operator_repairs=False,
        enable_clock_repairs=False,
        enable_reset_repairs=False,
        require_liveness_checks=getattr(args, "require_liveness_checks", False),
        require_admissibility=True,
        admissibility_tartar_root=getattr(args, "tartar_root", Path("TarTar-master")),
        admissibility_runner=getattr(args, "admissibility_runner", "auto"),
        admissibility_timeout=getattr(args, "admissibility_timeout", 3600),
        admissibility_output_dir=getattr(args, "admissibility_output_dir", None),
    )

    if args.command == "repair":
        mutation_hint = json.loads(read_text(args.mutation_json)) if args.mutation_json else None
        result = repair_model(args.model, args.properties, args.output_dir, config, mutation_hint)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0 if result.status in {"repaired", "already_satisfied"} else 2

    families = None
    if args.families:
        families = {item.strip() for item in args.families.split(",") if item.strip()}

    if args.command == "comparison":
        comparison = run_comparison_matrix(args.dataset_root, args.output_root, config, args.limit, families)
        copy_summary_to_doc(args.output_root / "comparison_summary.md", args.doc_output)
        print(
            json.dumps(
                {
                    "variants": len(comparison["variants"]),
                    "summary": str(args.output_root / "comparison_summary.md"),
                    "doc": str(args.doc_output) if args.doc_output else None,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if all(row["no_repair_count"] == 0 for row in comparison["variants"]) else 2

    config.use_mutation_hints = bool(getattr(args, "use_mutation_hints", False)) and not bool(
        getattr(args, "no_mutation_hints", False)
    )
    summary = run_dataset(args.dataset_root, args.output_root, config, args.limit, families)
    copy_summary_to_doc(args.output_root / "summary.md", args.doc_output)
    print(
        json.dumps(
            {
                "mutants": summary["mutant_count"],
                "repaired": summary["repaired_count"],
                "no_repair": summary["no_repair_count"],
                "summary": str(args.output_root / "summary.md"),
                "doc": str(args.doc_output) if args.doc_output else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if summary["no_repair_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
