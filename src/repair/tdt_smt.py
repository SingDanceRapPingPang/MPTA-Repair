"""TDT parsing, path-DAG analysis, and Z3 MaxSMT repair.

This module implements the core symbolic piece used by the repair prototype:
UPPAAL XML diagnostic traces are parsed into timed diagnostic traces, analyzed
for common prefixes, encoded as linear real arithmetic constraints, and solved
with Z3 Optimize over TarTar-style repair variables.  The solver first tries
quantifier elimination for the universal path-blocking condition and falls
back to an explicit lexicographic SMT search when needed.

The supported fragment is deliberately explicit: clock invariants/guards of the
form ``x <= c``, ``x >= c``, ``x < c``, ``x > c`` and ``x == c`` with integer
bounds, optional operator / clock-reference variation, resets ``x := 0``, and
safety properties such as
``A[] not P.l or x <= c``. Unsupported fragments are reported in the result.
"""

from __future__ import annotations

import ast
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree as ET

import z3

from src.repair.property_relations import _parse_boolean_expr, normalize_formula


CONSTRAINT_RE = re.compile(
    r"(?<![\w.])(?P<clock>[A-Za-z_]\w*)\s*(?P<op><=|>=|==|<|>)\s*"
    r"(?P<bound>[A-Za-z_]\w*(?:\s*[+\-]\s*(?:[A-Za-z_]\w*|-?\d+))+|[A-Za-z_]\w*|-?\d+)"
)
RESET_RE = re.compile(r"(?<![\w.])(?P<clock>[A-Za-z_]\w*)\s*:=\s*0\b")
ASSIGNMENT_RE = re.compile(r"(?<![<>=!])\b(?P<var>[A-Za-z_]\w*)\s*(?::=|=)\s*(?P<expr>[^,;]+)")
INSTANCE_NAME_RE = r"[A-Za-z_]\w*(?:\(\d+\))?"
QUALIFIED_NAME_RE = rf"{INSTANCE_NAME_RE}(?:\.[A-Za-z_]\w*)?"
LOCATION_RE = re.compile(rf"\b(?P<template>{INSTANCE_NAME_RE})\.(?P<location>[A-Za-z_]\w*)\b")


@dataclass(frozen=True)
class ClockConstraint:
    owner_id: str
    owner_kind: str
    owner_name: str
    label_kind: str
    text: str
    clock: str
    operator: str
    bound: int | None
    bound_text: str = ""

    @property
    def site_key(self) -> str:
        return (
            f"{self.owner_kind}:{self.owner_id}:{self.label_kind}:"
            f"{self.clock}:{self.operator}:{self.bound_text or self.bound}"
        )


@dataclass(frozen=True)
class TraceLocation:
    id: str
    process: str
    name: str
    invariant: str
    urgent: bool = False


@dataclass(frozen=True)
class TraceEdge:
    id: str
    process: str
    source: str
    target: str
    guard: str
    sync: str
    update: str

    @property
    def owner_name(self) -> str:
        return f"{self.source.split('.', 1)[-1]}->{self.target.split('.', 1)[-1]}"


@dataclass(frozen=True)
class TraceNode:
    id: str
    locations: tuple[str, ...]
    dbm_id: str | None = None
    variable_vector_id: str | None = None


@dataclass(frozen=True)
class ClockDifferenceBound:
    clock1: str
    clock2: str
    bound: int
    comparator: str


@dataclass(frozen=True)
class TraceVariable:
    name: str
    id: str


@dataclass(frozen=True)
class TraceVariableState:
    variable_id: str
    value: str


@dataclass(frozen=True)
class TraceStep:
    source: str
    target: str
    edge_ids: tuple[str, ...]

    @property
    def signature(self) -> tuple[str, ...]:
        return self.edge_ids


@dataclass
class TimedDiagnosticTrace:
    path: str
    property_index: int
    property_formula: str
    clocks: tuple[str, ...]
    locations: dict[str, TraceLocation]
    edges: dict[str, TraceEdge]
    nodes: dict[str, TraceNode]
    dbms: dict[str, tuple[ClockDifferenceBound, ...]]
    variables: dict[str, TraceVariable]
    variable_vectors: dict[str, tuple[TraceVariableState, ...]]
    initial_node: str
    steps: list[TraceStep]
    unsupported: list[str] = field(default_factory=list)

    @property
    def terminal_node(self) -> TraceNode:
        if not self.steps:
            return self.nodes[self.initial_node]
        return self.nodes[self.steps[-1].target]

    @property
    def signature(self) -> tuple[tuple[str, ...], ...]:
        """Discrete TDT identity used by the repair refinement loop."""

        terminal = ("__terminal__", *self.terminal_node.locations)
        return tuple(step.signature for step in self.steps) + (terminal,)


@dataclass
class PathDAGStats:
    trace_count: int
    node_count: int
    edge_count: int
    shared_prefix_nodes: int
    total_trace_steps: int
    independent_universal_node_count: int = 0
    independent_universal_edge_count: int = 0
    encoded_universal_node_count: int = 0
    encoded_universal_edge_count: int = 0
    saved_universal_nodes: int = 0
    saved_universal_edges: int = 0
    universal_encoding: str = "path_dag_shared"
    feasibility_encoding: str = "per_trace_existential"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PathRelationReport:
    common_subpaths: list[dict] = field(default_factory=list)
    dominance_pairs: list[dict] = field(default_factory=list)
    dominated_trace_indices: list[int] = field(default_factory=list)
    clusters: list[dict] = field(default_factory=list)
    cluster_representative_indices: list[int] = field(default_factory=list)
    encoded_trace_indices: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SymbolicRepairChange:
    action: str
    owner_kind: str
    owner_name: str
    template: str
    label_kind: str
    clock: str
    operator: str
    old_bound: int | float
    new_bound: int | float
    site_key: str
    delta: int | float = 0
    new_clock: str | None = None
    new_operator: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


SymbolicBoundChange = SymbolicRepairChange


@dataclass
class SymbolicRepairResult:
    status: str
    changes: list[SymbolicRepairChange] = field(default_factory=list)
    elapsed_sec: float = 0.0
    objective: dict = field(default_factory=dict)
    dag: dict = field(default_factory=dict)
    path_relations: dict = field(default_factory=dict)
    trace_paths: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", value)


def _short_id(value: str) -> str:
    return value.split(".", 1)[-1]


def _trace_clock_name(value: str) -> str:
    return value.removeprefix("sys.")


def _fraction_to_number(value: Fraction) -> int | float:
    if value.denominator == 1:
        return value.numerator
    return float(value)


def _z3_numeric_to_fraction(value: z3.ExprRef) -> Fraction | None:
    if hasattr(value, "as_fraction"):
        try:
            return value.as_fraction()
        except (AttributeError, z3.Z3Exception):
            pass
    if hasattr(value, "as_long"):
        try:
            return Fraction(value.as_long(), 1)
        except (AttributeError, z3.Z3Exception):
            pass
    text = str(value)
    if text.startswith("(- ") and text.endswith(")"):
        inner = text[3:-1].strip()
        parsed = _z3_numeric_to_fraction(z3.RealVal(inner)) if "/" in inner or inner.replace(".", "", 1).isdigit() else None
        return -parsed if parsed is not None else None
    try:
        return Fraction(text)
    except ValueError:
        return None


def _z3_number(value: int | float) -> z3.ArithRef:
    return z3.RealVal(str(value))


def _safe_eval_int(expr: str, constants: dict[str, int]) -> int | None:
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
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
            left = eval_node(node.left)
            right = eval_node(node.right)
            if left is None or right is None:
                return None
            return left + right if isinstance(node.op, ast.Add) else left - right
        return None

    try:
        parsed = ast.parse(expr.strip(), mode="eval")
    except SyntaxError:
        return None
    return eval_node(parsed.body)


def _expression_identifiers(text: str) -> set[str]:
    return set(re.findall(r"\b[A-Za-z_]\w*\b", text or ""))


def _is_supported_bound_expression(text: str, clocks: set[str] | None = None) -> bool:
    expr = text.strip()
    if not re.fullmatch(r"[A-Za-z_]\w*|-?\d+|[A-Za-z_]\w*(?:\s*[+\-]\s*(?:[A-Za-z_]\w*|-?\d+))+", expr):
        return False
    if clocks and (_expression_identifiers(expr) & clocks):
        return False
    return True


def _resolve_bound_expression(text: str, constants: dict[str, int], clocks: set[str] | None = None) -> int | None:
    expr = text.strip()
    if not _is_supported_bound_expression(expr, clocks):
        return None
    return _safe_eval_int(expr, constants)


def constraints_from_text(
    text: str,
    owner_id: str,
    owner_kind: str,
    owner_name: str,
    label_kind: str,
    constants: dict[str, int] | None = None,
    clocks: set[str] | None = None,
) -> list[ClockConstraint]:
    constraints: list[ClockConstraint] = []
    for match in CONSTRAINT_RE.finditer(text or ""):
        clock = match.group("clock")
        if clocks is not None and clock not in clocks:
            continue
        bound_text = match.group("bound").strip()
        if not _is_supported_bound_expression(bound_text, clocks):
            continue
        bound = _resolve_bound_expression(bound_text, constants or {}, clocks)
        constraints.append(
            ClockConstraint(
                owner_id=owner_id,
                owner_kind=owner_kind,
                owner_name=owner_name,
                label_kind=label_kind,
                text=match.group(0),
                clock=clock,
                operator=match.group("op"),
                bound=bound,
                bound_text=bound_text,
            )
        )
    return constraints


def load_urgent_locations(model_path: Path) -> set[str]:
    root = ET.parse(model_path).getroot()
    urgent: set[str] = set()
    for template in root.findall("template"):
        template_name = (template.findtext("name") or "").strip()
        if not template_name:
            continue
        for location in template.findall("location"):
            if location.find("urgent") is None and location.find("committed") is None:
                continue
            location_name = (location.findtext("name") or location.get("id") or "").strip()
            if location_name:
                urgent.add(f"{template_name}.{location_name}")
    return urgent


DECL_RE = re.compile(
    r"\b(?P<const>const\s+)?(?P<type>int|bool|double|real)(?:\s*\[[^\]]+\])?\s+(?P<body>[^;]+);",
    re.DOTALL,
)
ASSIGN_RE = re.compile(r"(?<![<>=!])\b(?P<var>[A-Za-z_]\w*)\s*(?::=|=|\+\+|--)")
CLOCK_DECL_RE = re.compile(r"\bclock\s+([^;]+);", re.DOTALL)


def _split_decl_names(body: str) -> list[str]:
    names: list[str] = []
    for part in body.split(","):
        name = part.split("=", 1)[0].strip()
        name = re.split(r"\[", name, maxsplit=1)[0].strip()
        if re.fullmatch(r"[A-Za-z_]\w*", name):
            names.append(name)
    return names


def load_model_bound_environment(model_path: Path | None) -> tuple[dict[str, int], set[str], dict[str, str]]:
    if model_path is None:
        return {}, set(), {}
    try:
        root = ET.parse(model_path).getroot()
    except ET.ParseError:
        return {}, set(), {}
    declarations = [root.findtext("declaration") or ""]
    assignment_labels: list[str] = []
    for template in root.findall("template"):
        declarations.append(template.findtext("declaration") or "")
        assignment_labels.extend(label.text or "" for label in template.iter("label") if label.get("kind") == "assignment")
    declaration_text = "\n".join(declarations)
    declaration_text = re.sub(r"/\*.*?\*/", "", declaration_text, flags=re.DOTALL)
    declaration_text = re.sub(r"//.*", "", declaration_text)
    clocks: set[str] = set()
    for match in CLOCK_DECL_RE.finditer(declaration_text):
        clocks.update(_split_decl_names(match.group(1)))
    assigned = {
        match.group("var")
        for text in assignment_labels
        for match in ASSIGN_RE.finditer(text or "")
    }
    pending: dict[str, str] = {}
    variable_types: dict[str, str] = {}
    for match in DECL_RE.finditer(declaration_text):
        raw_type = match.group("type")
        var_type = "Int"
        if raw_type == "bool":
            var_type = "Bool"
        elif raw_type in {"double", "real"}:
            var_type = "Real"
        for part in match.group("body").split(","):
            name_part, expr = (part.split("=", 1) + [""])[:2] if "=" in part else (part, "")
            name = re.split(r"\[", name_part, maxsplit=1)[0].strip()
            if not re.fullmatch(r"[A-Za-z_]\w*", name):
                continue
            if name not in clocks:
                variable_types[name] = var_type
            if not expr:
                continue
            if name in clocks or (name in assigned and not match.group("const")):
                continue
            pending[name] = expr.strip()
    constants: dict[str, int] = {}
    changed = True
    while changed:
        changed = False
        for name, expr in list(pending.items()):
            value = _safe_eval_int(expr, constants)
            if value is not None:
                constants[name] = value
                del pending[name]
                changed = True
    return constants, clocks, variable_types


def parse_verifyta_trace(
    path: Path,
    property_index: int,
    property_formula: str,
    urgent_locations: set[str] | None = None,
) -> TimedDiagnosticTrace:
    urgent_locations = urgent_locations or set()
    root = ET.parse(path).getroot()
    clocks = []
    locations: dict[str, TraceLocation] = {}
    edges: dict[str, TraceEdge] = {}
    variables: dict[str, TraceVariable] = {}
    system = root.find("system")
    if system is None:
        raise ValueError(f"trace has no system section: {path}")
    for clock in system.findall("clock"):
        name = clock.get("name", "")
        clock_id = clock.get("id", "")
        clock_name = _trace_clock_name(clock_id or name)
        if clock_name and not clock_name.startswith("#"):
            clocks.append(clock_name)
    for variable in system.findall("variable"):
        name = variable.get("name", "")
        variable_id = variable.get("id", "")
        if name and variable_id:
            variables[variable_id] = TraceVariable(name=name.removeprefix("sys."), id=variable_id)
    for process in system.findall("process"):
        process_id = process.get("id") or process.get("name") or "process"
        for clock in process.findall("clock"):
            name = clock.get("name", "")
            clock_id = clock.get("id", "")
            clock_name = _trace_clock_name(clock_id or (f"{process_id}.{name}" if name else ""))
            if clock_name and not clock_name.startswith("#"):
                clocks.append(clock_name)
        for location in process.findall("location"):
            location_id = location.get("id") or f"{process_id}.{location.get('name', 'location')}"
            locations[location_id] = TraceLocation(
                id=location_id,
                process=process_id,
                name=location.get("name") or _short_id(location_id),
                invariant=location.text or "",
                urgent=location_id in urgent_locations,
            )
        for edge in process.findall("edge"):
            edge_id = edge.get("id") or f"{process_id}.edge"
            edges[edge_id] = TraceEdge(
                id=edge_id,
                process=process_id,
                source=edge.get("from") or "",
                target=edge.get("to") or "",
                guard=edge.findtext("guard") or "1",
                sync=edge.findtext("sync") or "tau",
                update=edge.findtext("update") or "1",
            )

    location_vectors: dict[str, tuple[str, ...]] = {}
    for vector in root.findall("location_vector"):
        vector_id = vector.get("id")
        if not vector_id:
            continue
        location_vectors[vector_id] = tuple((vector.get("locations") or "").split())

    nodes: dict[str, TraceNode] = {}
    for node in root.findall("node"):
        node_id = node.get("id")
        if not node_id:
            continue
        vector_id = (node.get("location_vector") or "").strip()
        nodes[node_id] = TraceNode(
            node_id,
            location_vectors.get(vector_id, tuple()),
            node.get("dbm_instance"),
            node.get("variable_vector"),
        )

    variable_vectors: dict[str, tuple[TraceVariableState, ...]] = {}
    for vector in root.findall("variable_vector"):
        vector_id = vector.get("id")
        if not vector_id:
            continue
        states = []
        for state in vector.findall("variable_state"):
            variable_id = state.get("variable")
            value = state.get("value")
            if variable_id is None or value is None:
                continue
            states.append(TraceVariableState(variable_id=variable_id, value=value))
        variable_vectors[vector_id] = tuple(states)

    dbms: dict[str, tuple[ClockDifferenceBound, ...]] = {}
    for dbm in root.findall("dbm_instance"):
        dbm_id = dbm.get("id")
        if not dbm_id:
            continue
        bounds: list[ClockDifferenceBound] = []
        for bound in dbm.findall("clockbound"):
            raw_bound = bound.get("bound")
            if raw_bound is None or raw_bound == "inf":
                continue
            try:
                bound_value = int(raw_bound)
            except ValueError:
                continue
            bounds.append(
                ClockDifferenceBound(
                    clock1=_trace_clock_name(bound.get("clock1") or ""),
                    clock2=_trace_clock_name(bound.get("clock2") or ""),
                    bound=bound_value,
                    comparator=bound.get("comp") or "<=",
                )
            )
        dbms[dbm_id] = tuple(bounds)

    steps = [
        TraceStep(
            source=transition.get("from") or "",
            target=transition.get("to") or "",
            edge_ids=tuple((transition.get("edges") or "").split()),
        )
        for transition in root.findall("transition")
    ]
    return TimedDiagnosticTrace(
        path=str(path),
        property_index=property_index,
        property_formula=property_formula,
        clocks=tuple(clocks),
        locations=locations,
        edges=edges,
        nodes=nodes,
        dbms=dbms,
        variables=variables,
        variable_vectors=variable_vectors,
        initial_node=root.get("initial_node") or (steps[0].source if steps else ""),
        steps=steps,
    )


def collect_verifyta_traces(
    model_path: Path,
    query_path: Path,
    properties: list[str],
    violated_indices: list[int],
    verifyta_path: Path,
    output_dir: Path,
    timeout: int,
    max_traces_per_property: int | None = None,
    known_signatures: dict[int, set[tuple[tuple[str, ...], ...]]] | None = None,
) -> tuple[list[Path], list[str]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    trace_paths: list[Path] = []
    notes: list[str] = []
    search_orders = ["0", "1", "2", "3", "4"]
    for index in violated_indices:
        seen_signatures: set[tuple[tuple[str, ...], ...]] = set()
        known_for_property = known_signatures.setdefault(index, set()) if known_signatures is not None else None
        target_new_traces = (
            len(search_orders)
            if max_traces_per_property is None or max_traces_per_property <= 0
            else max(1, max_traces_per_property)
        )
        added_for_property = 0
        for attempt in range(len(search_orders)):
            prefix = output_dir / f"property_{index}_trace_s{attempt}"
            for old_trace in output_dir.glob(f"property_{index}_trace_s{attempt}*.xml"):
                old_trace.unlink(missing_ok=True)
            command = [
                str(verifyta_path),
                "-q",
                "-s",
                "-t",
                "1",
                "-o",
                search_orders[attempt % len(search_orders)],
                "-X",
                str(prefix),
                "--query-index",
                str(index - 1),
                str(model_path),
                str(query_path),
            ]
            start = time.time()
            proc = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
            elapsed = round(time.time() - start, 3)
            (output_dir / f"property_{index}_verifyta_trace_s{attempt}.txt").write_text(proc.stdout, encoding="utf-8")
            matches = sorted(output_dir.glob(f"property_{index}_trace_s{attempt}*.xml"))
            path = matches[0] if matches else output_dir / f"property_{index}_trace_s{attempt}{index}.xml"
            if path.exists():
                try:
                    trace = parse_verifyta_trace(path, index, properties[index - 1])
                    signature = trace.signature
                except Exception:
                    signature = ((str(path),),)
                if signature in seen_signatures:
                    notes.append(f"skipped duplicate TDT XML for property {index}: {path}")
                    continue
                if known_for_property is not None and signature in known_for_property:
                    notes.append(f"skipped already known TDT XML for property {index}: {path}")
                    continue
                seen_signatures.add(signature)
                if known_for_property is not None:
                    known_for_property.add(signature)
                trace_paths.append(path)
                added_for_property += 1
                notes.append(f"generated TDT XML for property {index} in {elapsed}s: {path}")
                if added_for_property >= target_new_traces:
                    break
            else:
                notes.append(f"verifyta did not produce TDT XML for property {index} on attempt {attempt + 1}")
    return trace_paths, notes


class PathDAG:
    def __init__(self, traces: list[TimedDiagnosticTrace], use_dbm_constraints: bool = False) -> None:
        self.traces = traces
        self.use_dbm_constraints = use_dbm_constraints
        self.nodes: set[tuple[tuple[str, ...], ...]] = {tuple()}
        self.edges: dict[tuple[tuple[tuple[str, ...], ...], tuple[str, ...]], tuple[tuple[str, ...], ...]] = {}
        self.trace_terminal: dict[int, tuple[tuple[str, ...], ...]] = {}
        self.trace_prefixes: dict[int, list[tuple[tuple[str, ...], ...]]] = {}
        self.prefix_representatives: dict[tuple[tuple[str, ...], ...], tuple[int, str]] = {}
        self.edge_representatives: dict[
            tuple[tuple[tuple[str, ...], ...], tuple[str, ...]],
            tuple[int, int],
        ] = {}
        self.prefix_counts: dict[tuple[tuple[str, ...], ...], int] = {tuple(): 0}
        self.prefix_conflicts: list[dict] = []
        self.edge_conflicts: list[dict] = []
        self.node_ids: dict[tuple[tuple[str, ...], ...], str] = {}
        self.edge_ids: dict[tuple[tuple[tuple[str, ...], ...], tuple[str, ...]], str] = {}
        for trace_index, trace in enumerate(traces):
            node_ids = [trace.initial_node] + [step.target for step in trace.steps]
            prefix: tuple[tuple[str, ...], ...] = tuple()
            prefixes = [prefix]
            self.prefix_counts[prefix] = self.prefix_counts.get(prefix, 0) + 1
            self._set_prefix_representative(prefix, trace_index, node_ids[0])
            for step_index, step in enumerate(trace.steps):
                signature = step.signature
                next_prefix = prefix + (signature,)
                self.nodes.add(next_prefix)
                self.edges[(prefix, signature)] = next_prefix
                self._set_edge_representative((prefix, signature), trace_index, step_index)
                prefix = next_prefix
                prefixes.append(prefix)
                self.prefix_counts[prefix] = self.prefix_counts.get(prefix, 0) + 1
                self._set_prefix_representative(prefix, trace_index, node_ids[step_index + 1])
            self.trace_terminal[trace_index] = prefix
            self.trace_prefixes[trace_index] = prefixes
        ordered_nodes = sorted(self.nodes, key=lambda value: (len(value), value))
        self.node_ids = {node: f"p{index}" for index, node in enumerate(ordered_nodes)}
        ordered_edges = sorted(self.edges, key=lambda edge: (len(edge[0]), edge[0], edge[1]))
        self.edge_ids = {edge: f"e{index}" for index, edge in enumerate(ordered_edges)}

    def _node_semantics(self, trace_index: int, node_id: str) -> tuple:
        trace = self.traces[trace_index]
        node = trace.nodes.get(node_id)
        if node is None:
            return ("missing", node_id)
        location_semantics = []
        for location_id in node.locations:
            location = trace.locations.get(location_id)
            location_semantics.append(
                (
                    location_id,
                    location.invariant if location is not None else "",
                    bool(location.urgent) if location is not None else False,
                )
            )
        dbm_semantics = tuple()
        if self.use_dbm_constraints and node.dbm_id:
            dbm_semantics = tuple(
                sorted(
                    (bound.clock1, bound.clock2, bound.comparator, bound.bound)
                    for bound in trace.dbms.get(node.dbm_id, tuple())
                )
            )
        return (tuple(location_semantics), dbm_semantics)

    def _edge_semantics(self, trace_index: int, step_index: int) -> tuple:
        trace = self.traces[trace_index]
        step = trace.steps[step_index]
        edge_semantics = []
        for edge_id in step.edge_ids:
            edge = trace.edges.get(edge_id)
            if edge is None:
                edge_semantics.append((edge_id, "missing"))
                continue
            edge_semantics.append((edge_id, edge.source, edge.target, edge.guard, edge.update, edge.sync))
        return tuple(edge_semantics)

    @property
    def sharing_safe(self) -> bool:
        return not self.prefix_conflicts and not self.edge_conflicts

    def _set_prefix_representative(
        self,
        prefix: tuple[tuple[str, ...], ...],
        trace_index: int,
        node_id: str,
    ) -> None:
        existing = self.prefix_representatives.get(prefix)
        if existing is None:
            self.prefix_representatives[prefix] = (trace_index, node_id)
            return
        existing_trace, existing_node = existing
        existing_semantics = self._node_semantics(existing_trace, existing_node)
        current_semantics = self._node_semantics(trace_index, node_id)
        if existing_semantics != current_semantics:
            self.prefix_conflicts.append(
                {
                    "prefix": self.prefix_label(prefix),
                    "left_trace": existing_trace,
                    "right_trace": trace_index,
                    "left_node": existing_node,
                    "right_node": node_id,
                }
            )

    def _set_edge_representative(
        self,
        edge_key: tuple[tuple[tuple[str, ...], ...], tuple[str, ...]],
        trace_index: int,
        step_index: int,
    ) -> None:
        existing = self.edge_representatives.get(edge_key)
        if existing is None:
            self.edge_representatives[edge_key] = (trace_index, step_index)
            return
        existing_trace, existing_step = existing
        if self._edge_semantics(existing_trace, existing_step) != self._edge_semantics(trace_index, step_index):
            self.edge_conflicts.append(
                {
                    "edge": self.signature_label(edge_key[1]),
                    "left_trace": existing_trace,
                    "right_trace": trace_index,
                    "left_step": existing_step,
                    "right_step": step_index,
                }
            )

    def skeleton(self, trace_index: int) -> tuple[tuple[str, ...], ...]:
        return tuple(step.signature for step in self.traces[trace_index].steps)

    def prefix_label(self, prefix: tuple[tuple[str, ...], ...]) -> str:
        return self.node_ids.get(prefix, "p?")

    def signature_label(self, signature: tuple[str, ...]) -> str:
        return "+".join(signature) if signature else "tau"

    def trace_repair_sites(self, trace_index: int) -> set[str]:
        trace = self.traces[trace_index]
        sites: set[str] = set()
        node_ids = [trace.initial_node] + [step.target for step in trace.steps]
        for node_id in node_ids:
            node = trace.nodes.get(node_id)
            if node is None:
                continue
            for location_id in node.locations:
                location = trace.locations.get(location_id)
                if location is None:
                    continue
                for site in constraints_from_text(
                    location.invariant,
                    owner_id=location.id,
                    owner_kind="location",
                    owner_name=location.name,
                    label_kind="invariant",
                ):
                    sites.add(site.site_key)
        for step in trace.steps:
            for edge_id in step.edge_ids:
                edge = trace.edges.get(edge_id)
                if edge is None:
                    continue
                for site in constraints_from_text(
                    edge.guard,
                    owner_id=edge.id,
                    owner_kind="transition",
                    owner_name=edge.owner_name,
                    label_kind="guard",
                ):
                    sites.add(site.site_key)
        return sites

    def common_subpaths(
        self,
        min_length: int = 2,
        max_length: int = 6,
        limit: int = 10,
    ) -> list[dict]:
        occurrences: dict[tuple[tuple[str, ...], ...], list[tuple[int, int]]] = {}
        for trace_index in range(len(self.traces)):
            skeleton = self.skeleton(trace_index)
            if len(skeleton) < min_length:
                continue
            upper = min(max_length, len(skeleton))
            for length in range(min_length, upper + 1):
                for start in range(0, len(skeleton) - length + 1):
                    key = skeleton[start : start + length]
                    occurrences.setdefault(key, []).append((trace_index, start))
        repeated = []
        for key, hits in occurrences.items():
            trace_indices = sorted({trace_index for trace_index, _start in hits})
            if len(hits) < 2 or len(trace_indices) < 2:
                continue
            repair_sites = set()
            for trace_index, start in hits:
                trace = self.traces[trace_index]
                for step in trace.steps[start : start + len(key)]:
                    for edge_id in step.edge_ids:
                        edge = trace.edges.get(edge_id)
                        if edge is None:
                            continue
                        for site in constraints_from_text(
                            edge.guard,
                            owner_id=edge.id,
                            owner_kind="transition",
                            owner_name=edge.owner_name,
                            label_kind="guard",
                        ):
                            repair_sites.add(site.site_key)
            repeated.append(
                {
                    "length": len(key),
                    "occurrences": len(hits),
                    "trace_count": len(trace_indices),
                    "traces": trace_indices,
                    "skeleton": [self.signature_label(signature) for signature in key],
                    "repair_sites": sorted(repair_sites)[:12],
                }
            )
        repeated.sort(key=lambda item: (-item["trace_count"], -item["occurrences"], -item["length"], item["skeleton"]))
        return repeated[:limit]

    def common_prefix_length(self, left: int, right: int) -> int:
        left_skeleton = self.skeleton(left)
        right_skeleton = self.skeleton(right)
        count = 0
        for left_step, right_step in zip(left_skeleton, right_skeleton):
            if left_step != right_step:
                break
            count += 1
        return count

    def cluster_traces(self, threshold: float = 0.62) -> list[dict]:
        site_sets = {index: self.trace_repair_sites(index) for index in range(len(self.traces))}
        skeleton_sets = {
            index: {self.signature_label(signature) for signature in self.skeleton(index)}
            for index in range(len(self.traces))
        }

        def jaccard(left: set[str], right: set[str]) -> float:
            if not left and not right:
                return 1.0
            union = left | right
            return len(left & right) / len(union) if union else 0.0

        clusters: list[list[int]] = []
        for trace_index in range(len(self.traces)):
            placed = False
            for cluster in clusters:
                representative = cluster[0]
                prefix = self.common_prefix_length(trace_index, representative)
                skeleton_similarity = jaccard(skeleton_sets[trace_index], skeleton_sets[representative])
                site_similarity = jaccard(site_sets[trace_index], site_sets[representative])
                score = 0.55 * skeleton_similarity + 0.35 * site_similarity
                if prefix:
                    score += 0.10
                if score >= threshold:
                    cluster.append(trace_index)
                    placed = True
                    break
            if not placed:
                clusters.append([trace_index])

        reports = []
        for cluster in clusters:
            representative = min(
                cluster,
                key=lambda index: (
                    len(self.skeleton(index)),
                    -len(site_sets[index]),
                    self.traces[index].property_index,
                    index,
                ),
            )
            members = sorted(cluster)
            reports.append(
                {
                    "representative": representative,
                    "members": members,
                    "size": len(members),
                    "property_indices": sorted({self.traces[index].property_index for index in members}),
                    "common_prefix_min": min(
                        (self.common_prefix_length(representative, index) for index in members if index != representative),
                        default=len(self.skeleton(representative)),
                    ),
                    "repair_site_count": len(set().union(*(site_sets[index] for index in members))) if members else 0,
                }
            )
        reports.sort(key=lambda item: (-item["size"], item["representative"]))
        return reports

    def stats(self) -> PathDAGStats:
        return PathDAGStats(
            trace_count=len(self.traces),
            node_count=len(self.nodes),
            edge_count=len(self.edges),
            shared_prefix_nodes=sum(1 for count in self.prefix_counts.values() if count > 1),
            total_trace_steps=sum(len(trace.steps) for trace in self.traces),
            independent_universal_node_count=sum(len(trace.steps) + 2 for trace in self.traces),
            independent_universal_edge_count=sum(len(trace.steps) for trace in self.traces),
        )


class TDTEncoder:
    OPERATOR_CHOICES = ("<=", ">=", "<", "==", ">")

    def __init__(
        self,
        traces: list[TimedDiagnosticTrace],
        max_bound_delta: int | None = None,
        enable_operator_variation: bool = False,
        enable_clock_reference_variation: bool = False,
        use_dbm_constraints: bool = False,
        blocked_assignments: list[dict[str, int | float]] | None = None,
        blocked_sites: set[str] | None = None,
        bound_constants: dict[str, int] | None = None,
        model_clocks: set[str] | None = None,
        model_variable_types: dict[str, str] | None = None,
        qe_timeout_ms: int = 500_000,
    ) -> None:
        if not traces:
            raise ValueError("at least one trace is required")
        self.traces = traces
        self.clocks = tuple(sorted({clock for trace in traces for clock in trace.clocks}))
        self.max_bound_delta = max_bound_delta
        self.enable_operator_variation = enable_operator_variation
        self.enable_clock_reference_variation = enable_clock_reference_variation
        self.use_dbm_constraints = use_dbm_constraints
        self.blocked_assignments = blocked_assignments or []
        self.blocked_sites = blocked_sites or set()
        self.bound_constants = bound_constants or {}
        self.model_clocks = model_clocks or set(self.clocks)
        self.qe_timeout_ms = max(1000, qe_timeout_ms)
        trace_variables = {
            variable.name
            for trace in traces
            for variable in trace.variables.values()
            if variable.name not in self.model_clocks
        }
        self.variable_types = {
            name: typ
            for name, typ in (model_variable_types or {}).items()
            if name not in self.model_clocks
        }
        for name in trace_variables:
            self.variable_types.setdefault(name, "Int")
        self.state_variables = tuple(sorted(self.variable_types))
        self.sites: dict[str, ClockConstraint] = {}
        self.operator_flags: dict[tuple[str, str], z3.BoolRef] = {}
        self.clock_flags: dict[tuple[str, str], z3.BoolRef] = {}

    def delta(self, site: ClockConstraint) -> z3.ArithRef:
        self.sites.setdefault(site.site_key, site)
        return z3.Real(f"bv__{re.sub(r'[^A-Za-z0-9_]', '_', site.site_key)}")

    def operator_flag(self, site: ClockConstraint, operator: str) -> z3.BoolRef:
        self.sites.setdefault(site.site_key, site)
        key = (site.site_key, operator)
        if key not in self.operator_flags:
            self.operator_flags[key] = z3.Bool(
                f"ov__{re.sub(r'[^A-Za-z0-9_]', '_', site.site_key)}__{operator.replace('=', 'e').replace('<', 'l').replace('>', 'g')}"
            )
        return self.operator_flags[key]

    def clock_flag(self, site: ClockConstraint, clock: str) -> z3.BoolRef:
        self.sites.setdefault(site.site_key, site)
        key = (site.site_key, clock)
        if key not in self.clock_flags:
            self.clock_flags[key] = z3.Bool(
                f"cv__{re.sub(r'[^A-Za-z0-9_]', '_', site.site_key)}__{re.sub(r'[^A-Za-z0-9_]', '_', clock)}"
            )
        return self.clock_flags[key]

    def _bound_expr(
        self,
        site: ClockConstraint,
        values: dict[str, z3.ArithRef],
    ) -> z3.ArithRef | None:
        parsed = self._parse_arith_expr(site.bound_text or "", values)
        if parsed is None and site.bound is not None:
            parsed = z3.IntVal(site.bound)
        if parsed is None:
            return None
        return self._coerce_real(parsed) + self.delta(site)

    def _constraints_from_text(
        self,
        text: str,
        owner_id: str,
        owner_kind: str,
        owner_name: str,
        label_kind: str,
    ) -> list[ClockConstraint]:
        constraints = constraints_from_text(
            text,
            owner_id=owner_id,
            owner_kind=owner_kind,
            owner_name=owner_name,
            label_kind=label_kind,
            constants=self.bound_constants,
            clocks=(self.model_clocks or set()) | set(self.clocks),
        )
        process = owner_id.split(".", 1)[0] if "." in owner_id else ""
        qualified: list[ClockConstraint] = []
        for site in constraints:
            clock = self._resolve_clock_name(site.clock, process)
            qualified.append(
                ClockConstraint(
                    owner_id=site.owner_id,
                    owner_kind=site.owner_kind,
                    owner_name=site.owner_name,
                    label_kind=site.label_kind,
                    text=site.text,
                    clock=clock,
                    operator=site.operator,
                    bound=site.bound,
                    bound_text=site.bound_text,
                )
            )
        return qualified

    def _resolve_clock_name(self, name: str, process: str = "") -> str:
        if name in self.clocks:
            return name
        if process and f"{process}.{name}" in self.clocks:
            return f"{process}.{name}"
        suffix_matches = [clock for clock in self.clocks if clock.endswith(f".{name}")]
        if len(suffix_matches) == 1:
            return suffix_matches[0]
        return name

    def _compare(self, value: z3.ArithRef, operator: str, bound: z3.ArithRef) -> z3.BoolRef:
        if operator == "<=":
            return value <= bound
        if operator == "<":
            return value < bound
        if operator == ">=":
            return value >= bound
        if operator == ">":
            return value > bound
        if operator == "==":
            return value == bound
        raise ValueError(f"unsupported operator: {operator}")

    def _selected_clock_value(
        self,
        clock_values: dict[str, z3.ArithRef],
        site: ClockConstraint,
    ) -> z3.ArithRef:
        value = clock_values[site.clock]
        if not self.enable_clock_reference_variation:
            return value
        selected = value
        for clock in self.clocks:
            if clock == site.clock:
                continue
            flag = self.clock_flag(site, clock)
            selected = z3.If(flag, clock_values[clock], selected)
        return selected

    def _atom(self, clock_values: dict[str, z3.ArithRef], site: ClockConstraint) -> z3.BoolRef:
        if site.clock not in clock_values:
            return z3.BoolVal(True)
        value = self._selected_clock_value(clock_values, site)
        bound = self._bound_expr(site, clock_values)
        if bound is None:
            return z3.BoolVal(True)
        atom = self._compare(value, site.operator, bound)
        if not self.enable_operator_variation:
            return z3.And(bound >= 0, atom)
        selected = atom
        for operator in self.OPERATOR_CHOICES:
            if operator == site.operator:
                continue
            flag = self.operator_flag(site, operator)
            selected = z3.If(flag, self._compare(value, operator, bound), selected)
        return z3.And(bound >= 0, selected)

    def _state_vars(self, prefix: str, node_index: int) -> dict[str, z3.ArithRef]:
        values = {clock: z3.Real(f"{prefix}__n{node_index}__{clock}") for clock in self.clocks}
        for name in self.state_variables:
            typ = self.variable_types.get(name, "Int")
            safe = _safe_name(name)
            if typ == "Bool":
                values[name] = z3.Int(f"{prefix}__n{node_index}__{safe}__bool")
            elif typ == "Real":
                values[name] = z3.Real(f"{prefix}__n{node_index}__{safe}")
            else:
                values[name] = z3.Int(f"{prefix}__n{node_index}__{safe}")
        return values

    def _clock_vars(self, prefix: str) -> dict[str, z3.ArithRef]:
        values = {clock: z3.Real(f"{prefix}__{_safe_name(clock)}") for clock in self.clocks}
        for name in self.state_variables:
            typ = self.variable_types.get(name, "Int")
            if typ == "Bool":
                values[name] = z3.Int(f"{prefix}__{_safe_name(name)}__bool")
            elif typ == "Real":
                values[name] = z3.Real(f"{prefix}__{_safe_name(name)}")
            else:
                values[name] = z3.Int(f"{prefix}__{_safe_name(name)}")
        return values

    def _dbm_value(self, clock: str, clock_values: dict[str, z3.ArithRef]) -> z3.ArithRef | None:
        if clock == "#t(0)":
            return z3.RealVal(0)
        if clock.startswith("#"):
            return None
        return clock_values.get(clock)

    def _coerce_real(self, value: z3.ArithRef) -> z3.ArithRef:
        return z3.ToReal(value) if z3.is_int(value) else value

    def _literal_for_variable(self, name: str, raw_value: str) -> z3.ArithRef | None:
        typ = self.variable_types.get(name, "Int")
        text = raw_value.strip()
        if typ == "Bool":
            if text.lower() in {"true", "1"}:
                return z3.IntVal(1)
            if text.lower() in {"false", "0"}:
                return z3.IntVal(0)
            return None
        if typ == "Real":
            try:
                return z3.RealVal(text)
            except z3.Z3Exception:
                return None
        try:
            return z3.IntVal(int(text))
        except ValueError:
            return None

    def trace_variable_values(self, trace: TimedDiagnosticTrace, node_id: str) -> dict[str, z3.ArithRef]:
        node = trace.nodes.get(node_id)
        if node is None or not node.variable_vector_id:
            return {}
        values: dict[str, z3.ArithRef] = {}
        for state in trace.variable_vectors.get(node.variable_vector_id, tuple()):
            variable = trace.variables.get(state.variable_id)
            if variable is None or variable.name not in self.state_variables:
                continue
            literal = self._literal_for_variable(variable.name, state.value)
            if literal is not None:
                values[variable.name] = literal
        return values

    def _parse_arith_expr(
        self,
        text: str,
        values: dict[str, z3.ArithRef],
    ) -> z3.ArithRef | None:
        expr = text.strip()
        if not expr:
            return None
        if expr in self.bound_constants:
            return z3.IntVal(self.bound_constants[expr])
        try:
            parsed = ast.parse(expr, mode="eval")
        except SyntaxError:
            return None

        def eval_node(node: ast.AST) -> z3.ArithRef | None:
            def dotted_name(value: ast.AST) -> str | None:
                if isinstance(value, ast.Name):
                    return value.id
                if isinstance(value, ast.Attribute):
                    prefix = dotted_name(value.value)
                    return f"{prefix}.{value.attr}" if prefix else None
                return None

            if isinstance(node, ast.Constant):
                if isinstance(node.value, bool):
                    return z3.IntVal(1 if node.value else 0)
                if isinstance(node.value, int):
                    return z3.IntVal(node.value)
                if isinstance(node.value, float):
                    return z3.RealVal(str(node.value))
            if isinstance(node, ast.Name):
                if node.id in values:
                    return values[node.id]
                if node.id in self.bound_constants:
                    return z3.IntVal(self.bound_constants[node.id])
                resolved = self._resolve_clock_name(node.id)
                if resolved in values:
                    return values[resolved]
                return None
            if isinstance(node, ast.Attribute):
                name = dotted_name(node)
                if name is None:
                    return None
                if name in values:
                    return values[name]
                resolved = self._resolve_clock_name(name)
                if resolved in values:
                    return values[resolved]
                return None
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub, ast.Not)):
                value = eval_node(node.operand)
                if value is None:
                    return None
                if isinstance(node.op, ast.Not):
                    return z3.If(value == 0, z3.IntVal(1), z3.IntVal(0))
                return value if isinstance(node.op, ast.UAdd) else -value
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv)):
                left = eval_node(node.left)
                right = eval_node(node.right)
                if left is None or right is None:
                    return None
                if isinstance(node.op, ast.Add):
                    return left + right
                if isinstance(node.op, ast.Sub):
                    return left - right
                if isinstance(node.op, ast.Mult):
                    return left * right
                if isinstance(node.op, (ast.Div, ast.FloorDiv)):
                    return left / right
            return None

        return eval_node(parsed.body)

    def _bound_side_expr(self, text: str, values: dict[str, z3.ArithRef]) -> z3.ArithRef | None:
        rewritten = text
        rewritten_values: dict[str, z3.ArithRef] = {}
        for index, name in enumerate(sorted(values, key=len, reverse=True)):
            if not re.search(rf"(?<![\w.]){re.escape(name)}(?![\w.])", rewritten):
                continue
            safe_name = f"__clock_ref_{index}"
            rewritten = re.sub(rf"(?<![\w.]){re.escape(name)}(?![\w.])", safe_name, rewritten)
            rewritten_values[safe_name] = values[name]
        if rewritten_values:
            merged_values = dict(values)
            merged_values.update(rewritten_values)
            parsed_rewritten = self._parse_arith_expr(rewritten, merged_values)
            if parsed_rewritten is not None:
                return parsed_rewritten
        parsed = self._parse_arith_expr(text, values)
        if parsed is not None:
            return parsed
        stripped = text.strip()
        if re.fullmatch(r"-?\d+", stripped):
            return z3.IntVal(int(stripped))
        return None

    def _compare_formula_values(self, left: z3.ArithRef, operator: str, right: z3.ArithRef) -> z3.BoolRef:
        if z3.is_real(left) or z3.is_real(right):
            left = self._coerce_real(left)
            right = self._coerce_real(right)
        if operator == "<=":
            return left <= right
        if operator == "<":
            return left < right
        if operator == ">=":
            return left >= right
        if operator == ">":
            return left > right
        if operator == "==":
            return left == right
        if operator == "!=":
            return left != right
        raise ValueError(f"unsupported operator: {operator}")

    def encode_dbm_constraints(
        self,
        trace: TimedDiagnosticTrace,
        node_id: str,
        clock_values: dict[str, z3.ArithRef],
    ) -> list[z3.BoolRef]:
        if not self.use_dbm_constraints:
            return []
        node = trace.nodes.get(node_id)
        if node is None or not node.dbm_id:
            return []
        constraints: list[z3.BoolRef] = []
        for bound in trace.dbms.get(node.dbm_id, tuple()):
            left = self._dbm_value(bound.clock1, clock_values)
            right = self._dbm_value(bound.clock2, clock_values)
            if left is None or right is None:
                continue
            diff = left - right
            if bound.comparator == "<":
                constraints.append(diff < bound.bound)
            else:
                constraints.append(diff <= bound.bound)
        return constraints

    def _state_domain_constraints(self, values: dict[str, z3.ArithRef]) -> list[z3.BoolRef]:
        constraints = [values[clock] >= 0 for clock in self.clocks if clock in values]
        for name in self.state_variables:
            if self.variable_types.get(name) == "Bool" and name in values:
                constraints.append(z3.Or(values[name] == 0, values[name] == 1))
        return constraints

    def _initial_variable_constraints(
        self,
        trace: TimedDiagnosticTrace,
        values: dict[str, z3.ArithRef],
    ) -> list[z3.BoolRef]:
        constraints: list[z3.BoolRef] = []
        for name, literal in self.trace_variable_values(trace, trace.initial_node).items():
            if name in values:
                constraints.append(values[name] == literal)
        return constraints

    def _edge_assignment_constraints(
        self,
        edge_text: str,
        source_state: dict[str, z3.ArithRef],
        target_state: dict[str, z3.ArithRef],
        assigned: set[str],
    ) -> list[z3.BoolRef]:
        constraints: list[z3.BoolRef] = []
        for match in ASSIGNMENT_RE.finditer(edge_text or ""):
            name = match.group("var")
            if name not in self.state_variables or name not in target_state:
                continue
            expr = self._parse_arith_expr(match.group("expr"), source_state)
            if expr is None:
                assigned.add(name)
                continue
            constraints.append(target_state[name] == expr)
            assigned.add(name)
        return constraints

    def encode_node_constraints(
        self,
        trace: TimedDiagnosticTrace,
        node_id: str,
        clock_values: dict[str, z3.ArithRef],
    ) -> list[z3.BoolRef]:
        constraints: list[z3.BoolRef] = self._state_domain_constraints(clock_values)
        constraints.extend(self.encode_dbm_constraints(trace, node_id, clock_values))
        node = trace.nodes.get(node_id)
        if node is None:
            return constraints
        for location_id in node.locations:
            location = trace.locations.get(location_id)
            if location is None:
                continue
            for site in self._constraints_from_text(
                location.invariant,
                owner_id=location.id,
                owner_kind="location",
                owner_name=location.name,
                label_kind="invariant",
            ):
                constraints.append(self._atom(clock_values, site))
        return constraints

    def encode_edge_constraints(
        self,
        trace: TimedDiagnosticTrace,
        step_index: int,
        source_state: dict[str, z3.ArithRef],
        target_state: dict[str, z3.ArithRef],
        delay: z3.ArithRef,
    ) -> list[z3.BoolRef]:
        constraints: list[z3.BoolRef] = [delay >= 0]
        node_ids = [trace.initial_node] + [step.target for step in trace.steps]
        source_node = trace.nodes[node_ids[step_index]]
        if any(
            (trace.locations.get(location_id) and trace.locations[location_id].urgent)
            for location_id in source_node.locations
        ):
            constraints.append(delay == 0)
        delayed = dict(source_state)
        for clock in self.clocks:
            delayed[clock] = source_state[clock] + delay
        for location_id in source_node.locations:
            location = trace.locations.get(location_id)
            if location is None:
                continue
            for site in self._constraints_from_text(
                location.invariant,
                owner_id=location.id,
                owner_kind="location",
                owner_name=location.name,
                label_kind="invariant",
            ):
                constraints.append(self._atom(delayed, site))

        resets: set[str] = set()
        assigned_variables: set[str] = set()
        step = trace.steps[step_index]
        for edge_id in step.edge_ids:
            edge = trace.edges.get(edge_id)
            if edge is None:
                trace.unsupported.append(f"missing edge in trace: {edge_id}")
                continue
            for site in self._constraints_from_text(
                edge.guard,
                owner_id=edge.id,
                owner_kind="transition",
                owner_name=edge.owner_name,
                label_kind="guard",
            ):
                constraints.append(self._atom(delayed, site))
            resets.update(match.group("clock") for match in RESET_RE.finditer(edge.update or ""))
            constraints.extend(
                self._edge_assignment_constraints(edge.update, source_state, target_state, assigned_variables)
            )

        for clock in self.clocks:
            if clock in resets:
                constraints.append(target_state[clock] == 0)
            else:
                constraints.append(target_state[clock] == delayed[clock])
        for name in self.state_variables:
            if name not in assigned_variables and name in source_state and name in target_state:
                constraints.append(target_state[name] == source_state[name])
        return constraints

    def encode_terminal_observation_constraints(
        self,
        trace: TimedDiagnosticTrace,
        entry_state: dict[str, z3.ArithRef],
        observation_state: dict[str, z3.ArithRef],
        delay: z3.ArithRef,
    ) -> list[z3.BoolRef]:
        constraints: list[z3.BoolRef] = [delay >= 0]
        terminal_node = trace.terminal_node
        if any(
            (trace.locations.get(location_id) and trace.locations[location_id].urgent)
            for location_id in terminal_node.locations
        ):
            constraints.append(delay == 0)
        for clock in self.clocks:
            constraints.append(observation_state[clock] == entry_state[clock] + delay)
            constraints.append(observation_state[clock] >= 0)
        for name in self.state_variables:
            if name in entry_state and name in observation_state:
                constraints.append(observation_state[name] == entry_state[name])
        for location_id in terminal_node.locations:
            location = trace.locations.get(location_id)
            if location is None:
                continue
            for site in self._constraints_from_text(
                location.invariant,
                owner_id=location.id,
                owner_kind="location",
                owner_name=location.name,
                label_kind="invariant",
            ):
                constraints.append(self._atom(entry_state, site))
                constraints.append(self._atom(observation_state, site))
        return constraints

    def encode_trace_constraints(
        self,
        trace: TimedDiagnosticTrace,
        prefix: str,
    ) -> tuple[list[z3.BoolRef], list[z3.ExprRef], dict[int, dict[str, z3.ArithRef]]]:
        constraints: list[z3.BoolRef] = []
        quantified: list[z3.ExprRef] = []
        state_vars: dict[int, dict[str, z3.ArithRef]] = {}
        terminal_observation_index = len(trace.steps) + 1
        for node_index in range(terminal_observation_index + 1):
            state_vars[node_index] = self._state_vars(prefix, node_index)
            quantified.extend(state_vars[node_index].values())
            constraints.extend(self._state_domain_constraints(state_vars[node_index]))
        for clock in self.clocks:
            constraints.append(state_vars[0][clock] == 0)
        constraints.extend(self._initial_variable_constraints(trace, state_vars[0]))

        node_ids = [trace.initial_node] + [step.target for step in trace.steps]
        constraints.extend(self.encode_dbm_constraints(trace, node_ids[0], state_vars[0]))
        for step_index, step in enumerate(trace.steps):
            delay = z3.Real(f"{prefix}__d{step_index}")
            quantified.append(delay)
            constraints.append(delay >= 0)
            if any(
                (trace.locations.get(location_id) and trace.locations[location_id].urgent)
                for location_id in trace.nodes[node_ids[step_index]].locations
            ):
                constraints.append(delay == 0)
            source_state = state_vars[step_index]
            delayed = dict(source_state)
            for clock in self.clocks:
                delayed[clock] = source_state[clock] + delay
            target_state = state_vars[step_index + 1]

            for location_id in trace.nodes[node_ids[step_index]].locations:
                location = trace.locations.get(location_id)
                if location is None:
                    continue
                for site in self._constraints_from_text(
                    location.invariant,
                    owner_id=location.id,
                    owner_kind="location",
                    owner_name=location.name,
                    label_kind="invariant",
                ):
                    constraints.append(self._atom(source_state, site))
                    constraints.append(self._atom(delayed, site))

            resets: set[str] = set()
            assigned_variables: set[str] = set()
            for edge_id in step.edge_ids:
                edge = trace.edges.get(edge_id)
                if edge is None:
                    trace.unsupported.append(f"missing edge in trace: {edge_id}")
                    continue
                for site in self._constraints_from_text(
                    edge.guard,
                    owner_id=edge.id,
                    owner_kind="transition",
                    owner_name=edge.owner_name,
                    label_kind="guard",
                ):
                    constraints.append(self._atom(delayed, site))
                resets.update(match.group("clock") for match in RESET_RE.finditer(edge.update or ""))
                constraints.extend(
                    self._edge_assignment_constraints(edge.update, source_state, target_state, assigned_variables)
                )

            for clock in self.clocks:
                if clock in resets:
                    constraints.append(target_state[clock] == 0)
                else:
                    constraints.append(target_state[clock] == delayed[clock])
            for name in self.state_variables:
                if name not in assigned_variables and name in source_state and name in target_state:
                    constraints.append(target_state[name] == source_state[name])
            constraints.extend(self.encode_dbm_constraints(trace, node_ids[step_index + 1], target_state))

            for location_id in trace.nodes[node_ids[step_index + 1]].locations:
                location = trace.locations.get(location_id)
                if location is None:
                    continue
                for site in self._constraints_from_text(
                    location.invariant,
                    owner_id=location.id,
                    owner_kind="location",
                    owner_name=location.name,
                    label_kind="invariant",
                ):
                    constraints.append(self._atom(target_state, site))

        terminal_delay = z3.Real(f"{prefix}__d_terminal")
        quantified.append(terminal_delay)
        constraints.append(terminal_delay >= 0)
        terminal_entry = state_vars[len(trace.steps)]
        terminal_observation = state_vars[terminal_observation_index]
        terminal_node = trace.nodes[node_ids[-1]]
        if any(
            (trace.locations.get(location_id) and trace.locations[location_id].urgent)
            for location_id in terminal_node.locations
        ):
            constraints.append(terminal_delay == 0)
        for clock in self.clocks:
            constraints.append(terminal_observation[clock] == terminal_entry[clock] + terminal_delay)
        for name in self.state_variables:
            if name in terminal_entry and name in terminal_observation:
                constraints.append(terminal_observation[name] == terminal_entry[name])
        for location_id in terminal_node.locations:
            location = trace.locations.get(location_id)
            if location is None:
                continue
            for site in self._constraints_from_text(
                location.invariant,
                owner_id=location.id,
                owner_kind="location",
                owner_name=location.name,
                label_kind="invariant",
            ):
                constraints.append(self._atom(terminal_entry, site))
                constraints.append(self._atom(terminal_observation, site))
        return constraints, quantified, state_vars

    def _delay_sum(self, delays: list[z3.ArithRef], start: int, end: int) -> z3.ArithRef:
        terms = delays[start:end]
        if not terms:
            return z3.RealVal(0)
        return z3.simplify(z3.Sum(terms))

    def _trace_literal_state(
        self,
        trace: TimedDiagnosticTrace,
        node_id: str,
        clock_exprs: dict[str, z3.ArithRef],
    ) -> dict[str, z3.ArithRef]:
        values = dict(clock_exprs)
        values.update(self.trace_variable_values(trace, node_id))
        return values

    def _edge_reset_clocks(self, trace: TimedDiagnosticTrace, step: TraceStep) -> set[str]:
        resets: set[str] = set()
        for edge_id in step.edge_ids:
            edge = trace.edges.get(edge_id)
            if edge is None:
                trace.unsupported.append(f"missing edge in trace: {edge_id}")
                continue
            resets.update(
                self._resolve_clock_name(match.group("clock"), edge.process)
                for match in RESET_RE.finditer(edge.update or "")
                if self._resolve_clock_name(match.group("clock"), edge.process) in self.clocks
            )
        return resets

    def encode_trace_constraints_delay_substituted(
        self,
        trace: TimedDiagnosticTrace,
        prefix: str,
    ) -> tuple[list[z3.BoolRef], list[z3.ExprRef], dict[int, dict[str, z3.ArithRef]]]:
        """Encode a TDT in the same style as TarTar's QE input.

        TarTar's ``ClockSmt2.getClockValue`` replaces each clock value by the
        sum of the delay variables since the last reset, and the QE formula
        quantifies only those delay variables.  UPPAAL ``variable_state`` values
        are concrete trace values, so ordinary variables are read from the XML
        trace instead of being universally quantified at every state.
        """

        constraints: list[z3.BoolRef] = []
        quantified: list[z3.ExprRef] = []
        state_values: dict[int, dict[str, z3.ArithRef]] = {}
        node_ids = [trace.initial_node] + [step.target for step in trace.steps]
        delays = [z3.Real(f"{prefix}__t0_{index}") for index in range(len(trace.steps))]
        terminal_delay = z3.Real(f"{prefix}__t0_terminal")
        quantified.extend(delays)
        quantified.append(terminal_delay)
        constraints.extend(delay >= 0 for delay in delays)
        constraints.append(terminal_delay >= 0)

        last_reset_index = {clock: 0 for clock in self.clocks}
        for node_index, node_id in enumerate(node_ids):
            clock_exprs = {
                clock: self._delay_sum(delays, last_reset_index[clock], node_index)
                for clock in self.clocks
            }
            state_values[node_index] = self._trace_literal_state(trace, node_id, clock_exprs)
            constraints.extend(self._state_domain_constraints(state_values[node_index]))
            constraints.extend(self.encode_dbm_constraints(trace, node_id, state_values[node_index]))
            node = trace.nodes[node_id]
            for location_id in node.locations:
                location = trace.locations.get(location_id)
                if location is None:
                    continue
                for site in self._constraints_from_text(
                    location.invariant,
                    owner_id=location.id,
                    owner_kind="location",
                    owner_name=location.name,
                    label_kind="invariant",
                ):
                    constraints.append(self._atom(state_values[node_index], site))

            if node_index == len(trace.steps):
                break

            step = trace.steps[node_index]
            source_node = trace.nodes[node_id]
            delay = delays[node_index]
            if any(
                (trace.locations.get(location_id) and trace.locations[location_id].urgent)
                for location_id in source_node.locations
            ):
                constraints.append(delay == 0)

            delayed_clock_exprs = {
                clock: self._delay_sum(delays, last_reset_index[clock], node_index + 1)
                for clock in self.clocks
            }
            delayed_state = dict(state_values[node_index])
            delayed_state.update(delayed_clock_exprs)
            constraints.extend(self._state_domain_constraints(delayed_state))
            for location_id in source_node.locations:
                location = trace.locations.get(location_id)
                if location is None:
                    continue
                for site in self._constraints_from_text(
                    location.invariant,
                    owner_id=location.id,
                    owner_kind="location",
                    owner_name=location.name,
                    label_kind="invariant",
                ):
                    constraints.append(self._atom(delayed_state, site))

            assigned_variables: set[str] = set()
            target_literals = self.trace_variable_values(trace, step.target)
            for edge_id in step.edge_ids:
                edge = trace.edges.get(edge_id)
                if edge is None:
                    trace.unsupported.append(f"missing edge in trace: {edge_id}")
                    continue
                for site in self._constraints_from_text(
                    edge.guard,
                    owner_id=edge.id,
                    owner_kind="transition",
                    owner_name=edge.owner_name,
                    label_kind="guard",
                ):
                    constraints.append(self._atom(delayed_state, site))
                constraints.extend(
                    self._edge_assignment_constraints(
                        edge.update,
                        state_values[node_index],
                        target_literals,
                        assigned_variables,
                    )
                )
            for name in self.state_variables:
                if name not in assigned_variables and name in state_values[node_index] and name in target_literals:
                    constraints.append(target_literals[name] == state_values[node_index][name])

            resets = self._edge_reset_clocks(trace, step)
            for clock in resets:
                last_reset_index[clock] = node_index + 1

        terminal_index = len(trace.steps) + 1
        terminal_entry = state_values[len(trace.steps)]
        terminal_clock_exprs = {
            clock: terminal_entry[clock] + terminal_delay
            for clock in self.clocks
            if clock in terminal_entry
        }
        terminal_observation = dict(terminal_entry)
        terminal_observation.update(terminal_clock_exprs)
        state_values[terminal_index] = terminal_observation
        terminal_node = trace.nodes[node_ids[-1]]
        if any(
            (trace.locations.get(location_id) and trace.locations[location_id].urgent)
            for location_id in terminal_node.locations
        ):
            constraints.append(terminal_delay == 0)
        constraints.extend(self._state_domain_constraints(terminal_observation))
        for location_id in terminal_node.locations:
            location = trace.locations.get(location_id)
            if location is None:
                continue
            for site in self._constraints_from_text(
                location.invariant,
                owner_id=location.id,
                owner_kind="location",
                owner_name=location.name,
                label_kind="invariant",
            ):
                constraints.append(self._atom(terminal_observation, site))
        return constraints, quantified, state_values

    def _comparison_for_formula(
        self,
        match: re.Match[str],
        values: dict[str, z3.ArithRef],
    ) -> z3.BoolRef | None:
        left = match.group("left")
        op = match.group("op")
        right = match.group("right")
        left_expr = self._bound_side_expr(left, values)
        right_expr = self._bound_side_expr(right, values)
        if left_expr is None or right_expr is None:
            return None
        return self._compare_formula_values(left_expr, op, right_expr)

    def property_formula_for_state(
        self,
        formula: str,
        active_locations: tuple[str, ...],
        clock_values: dict[str, z3.ArithRef],
    ) -> tuple[z3.BoolRef | None, list[str]]:
        unsupported: list[str] = []
        text = normalize_formula(formula)
        env: dict[str, z3.ExprRef] = {}

        identifier = QUALIFIED_NAME_RE
        arith_side = rf"(?:{identifier}|-?\d+)(?:\s*[+\-]\s*(?:{identifier}|-?\d+))*"
        comparison_re = re.compile(
            rf"(?<![\w.])(?P<left>{arith_side})\s*(?P<op><=|>=|==|!=|<|>)\s*(?P<right>{arith_side})(?![\w.])"
        )
        replacements: list[tuple[int, int, str]] = []
        for match in comparison_re.finditer(text):
            comparison = self._comparison_for_formula(match, clock_values)
            if comparison is None:
                unsupported.append(match.group(0))
                continue
            symbol = f"cmp__{match.start()}_{match.end()}"
            env[symbol] = comparison
            replacements.append((match.start(), match.end(), symbol))
        for start, end, symbol in reversed(replacements):
            text = text[:start] + symbol + text[end:]

        replacements = []
        for match in LOCATION_RE.finditer(text):
            location = f"{match.group('template')}.{match.group('location')}"
            symbol = f"loc__{match.start()}_{match.end()}"
            env[symbol] = z3.BoolVal(location in active_locations)
            replacements.append((match.start(), match.end(), symbol))
        for start, end, symbol in reversed(replacements):
            text = text[:start] + symbol + text[end:]
        try:
            return _parse_boolean_expr(text, env), unsupported
        except ValueError as exc:
            unsupported.append(str(exc))
            return None, unsupported

    def encode_dag_universal_obligations(
        self,
        dag: PathDAG,
        trace_indices: list[int],
        prefix: str,
    ) -> tuple[list[z3.ExprRef], list[z3.BoolRef], dict, list[str]]:
        """Encode universal path obligations on a shared prefix DAG.

        The quantified clock variables are attached to DAG prefix nodes rather
        than to each TDT.  Each trace obligation still uses only the blocks on
        its own path, so branches do not accidentally constrain one another.
        """

        notes: list[str] = []
        used_nodes: set[tuple[tuple[str, ...], ...]] = set()
        used_edges: set[tuple[tuple[tuple[str, ...], ...], tuple[str, ...]]] = set()
        terminal_prefixes: set[tuple[tuple[str, ...], ...]] = set()
        for trace_index in trace_indices:
            prefixes = dag.trace_prefixes[trace_index]
            used_nodes.update(prefixes)
            terminal_prefixes.add(prefixes[-1])
            trace = self.traces[trace_index]
            for step_index, step in enumerate(trace.steps):
                used_edges.add((prefixes[step_index], step.signature))

        node_vars: dict[tuple[tuple[str, ...], ...], dict[str, z3.ArithRef]] = {}
        node_blocks: dict[tuple[tuple[str, ...], ...], z3.BoolRef] = {}
        quantified: list[z3.ExprRef] = []
        for node in sorted(used_nodes, key=lambda value: (len(value), value)):
            node_name = f"{prefix}__{dag.prefix_label(node)}"
            values = self._clock_vars(node_name)
            node_vars[node] = values
            quantified.extend(values.values())
            trace_index, node_id = dag.prefix_representatives[node]
            block_constraints = self.encode_node_constraints(self.traces[trace_index], node_id, values)
            if node == tuple():
                block_constraints.extend(values[clock] == 0 for clock in self.clocks)
                block_constraints.extend(self._initial_variable_constraints(self.traces[trace_index], values))
            node_blocks[node] = z3.And(*block_constraints) if block_constraints else z3.BoolVal(True)

        edge_blocks: dict[tuple[tuple[tuple[str, ...], ...], tuple[str, ...]], z3.BoolRef] = {}
        for edge_key in sorted(used_edges, key=lambda value: (len(value[0]), value[0], value[1])):
            source_prefix, signature = edge_key
            target_prefix = dag.edges[edge_key]
            edge_id = dag.edge_ids[edge_key]
            delay = z3.Real(f"{prefix}__{edge_id}__delay")
            quantified.append(delay)
            trace_index, step_index = dag.edge_representatives[edge_key]
            block_constraints = self.encode_edge_constraints(
                self.traces[trace_index],
                step_index,
                node_vars[source_prefix],
                node_vars[target_prefix],
                delay,
            )
            edge_blocks[edge_key] = z3.And(*block_constraints) if block_constraints else z3.BoolVal(True)

        terminal_vars: dict[tuple[tuple[str, ...], ...], dict[str, z3.ArithRef]] = {}
        terminal_blocks: dict[tuple[tuple[str, ...], ...], z3.BoolRef] = {}
        for terminal_prefix in sorted(terminal_prefixes, key=lambda value: (len(value), value)):
            terminal_name = f"{prefix}__{dag.prefix_label(terminal_prefix)}__terminal"
            values = self._clock_vars(terminal_name)
            terminal_vars[terminal_prefix] = values
            quantified.extend(values.values())
            delay = z3.Real(f"{terminal_name}__delay")
            quantified.append(delay)
            trace_index, _node_id = dag.prefix_representatives[terminal_prefix]
            block_constraints = self.encode_terminal_observation_constraints(
                self.traces[trace_index],
                node_vars[terminal_prefix],
                values,
                delay,
            )
            terminal_blocks[terminal_prefix] = z3.And(*block_constraints) if block_constraints else z3.BoolVal(True)

        universal_blocks: list[z3.BoolRef] = []
        for trace_index in trace_indices:
            trace = self.traces[trace_index]
            prefixes = dag.trace_prefixes[trace_index]
            antecedent_blocks: list[z3.BoolRef] = [node_blocks[prefix_node] for prefix_node in prefixes]
            for step_index, step in enumerate(trace.steps):
                antecedent_blocks.append(edge_blocks[(prefixes[step_index], step.signature)])
            terminal_prefix = prefixes[-1]
            antecedent_blocks.append(terminal_blocks[terminal_prefix])
            property_expr, unsupported = self.property_formula_for_state(
                trace.property_formula,
                trace.terminal_node.locations,
                terminal_vars[terminal_prefix],
            )
            if unsupported or property_expr is None:
                notes.extend([f"P{trace.property_index}: {item}" for item in unsupported])
                continue
            universal_blocks.append(z3.Implies(z3.And(*antecedent_blocks), property_expr))

        stats = {
            "encoded_trace_count": len(trace_indices),
            "encoded_node_count": len(used_nodes) + len(terminal_prefixes),
            "encoded_edge_count": len(used_edges),
            "terminal_observation_count": len(terminal_prefixes),
            "quantified_variable_count": len(quantified),
        }
        return quantified, universal_blocks, stats, notes

    def encode_per_trace_universal_obligations(
        self,
        trace_indices: list[int],
        prefix: str,
    ) -> tuple[list[z3.ExprRef], list[z3.BoolRef], dict, list[str]]:
        notes: list[str] = []
        quantified_count = 0
        universal_blocks: list[z3.BoolRef] = []
        for trace_index in trace_indices:
            trace = self.traces[trace_index]
            u_constraints, u_vars, u_state_vars = self.encode_trace_constraints_delay_substituted(
                trace,
                f"{prefix}{trace_index}",
            )
            terminal_index = len(trace.steps) + 1
            u_property_expr, unsupported = self.property_formula_for_state(
                trace.property_formula,
                trace.terminal_node.locations,
                u_state_vars[terminal_index],
            )
            if unsupported or u_property_expr is None:
                notes.extend([f"P{trace.property_index}: {item}" for item in unsupported])
                continue
            existential_clauses = u_constraints + [z3.Not(u_property_expr)]
            retained_u_vars, pruned_count = self._prune_quantified_vars(u_vars, existential_clauses)
            quantified_count += len(retained_u_vars)
            if pruned_count > 0:
                notes.append(
                    f"trace {trace_index}: pruned {pruned_count} unused quantified variable(s) before QE"
                )
            existential_body = z3.And(*existential_clauses)
            if retained_u_vars:
                universal_blocks.append(z3.Not(z3.Exists(retained_u_vars, existential_body)))
            else:
                universal_blocks.append(z3.Not(existential_body))
        stats = {
            "encoded_trace_count": len(trace_indices),
            "encoded_node_count": sum(len(self.traces[index].steps) + 2 for index in trace_indices),
            "encoded_edge_count": sum(len(self.traces[index].steps) for index in trace_indices),
            "terminal_observation_count": len(trace_indices),
            "quantified_variable_count": quantified_count,
        }
        return [], universal_blocks, stats, notes

    def _at_most_one(self, flags: list[z3.BoolRef]) -> list[z3.BoolRef]:
        constraints: list[z3.BoolRef] = []
        for left_index, left in enumerate(flags):
            for right in flags[left_index + 1 :]:
                constraints.append(z3.Not(z3.And(left, right)))
        return constraints

    def _contains_quantifier(self, expr: z3.ExprRef) -> bool:
        if z3.is_quantifier(expr):
            return True
        return any(self._contains_quantifier(expr.arg(index)) for index in range(expr.num_args()))

    def _z3_const_names(self, expr: z3.ExprRef) -> set[str]:
        names: set[str] = set()
        stack = [expr]
        while stack:
            current = stack.pop()
            if z3.is_const(current) and current.decl().kind() == z3.Z3_OP_UNINTERPRETED:
                names.add(current.decl().name())
                continue
            stack.extend(current.children())
        return names

    def _prune_quantified_vars(
        self,
        quantified: list[z3.ExprRef],
        clauses: list[z3.BoolRef],
    ) -> tuple[list[z3.ExprRef], int]:
        if not quantified:
            return quantified, 0
        used_names: set[str] = set()
        for clause in clauses:
            used_names.update(self._z3_const_names(clause))
        retained = [var for var in quantified if var.decl().name() in used_names]
        return retained, max(0, len(quantified) - len(retained))

    def quantifier_eliminated_constraints(
        self,
        constraints: list[z3.BoolRef],
        timeout_ms: int | None = None,
    ) -> list[z3.BoolRef] | None:
        """Eliminate the TarTar-style trace delay quantifiers.

        Match TarTar's effective Java QE pipeline used in Z3Call:
        simplify -> qe2 -> simplify -> propagate-ineqs -> propagate-values.
        """
        timeout = self.qe_timeout_ms if timeout_ms is None else max(1000, timeout_ms)
        goal = z3.Goal()
        goal.add(*constraints)
        try:
            tactic = z3.Then(
                "simplify",
                "qe2",
                "simplify",
                "propagate-ineqs",
                "propagate-values",
            )
            qe_result = z3.TryFor(tactic, timeout)(goal)
        except z3.Z3Exception:
            return None
        if len(qe_result) == 0:
            return None
        subgoal_exprs = [subgoal.as_expr() for subgoal in qe_result]
        expr = subgoal_exprs[0] if len(subgoal_exprs) == 1 else z3.Or(*subgoal_exprs)
        if self._contains_quantifier(expr):
            return None
        return [expr]

    def variation_constraints(self) -> list[z3.BoolRef]:
        constraints: list[z3.BoolRef] = []
        if self.enable_operator_variation:
            for site_key in self.sites:
                flags = [
                    flag
                    for (flag_site_key, _operator), flag in self.operator_flags.items()
                    if flag_site_key == site_key
                ]
                constraints.extend(self._at_most_one(flags))
        if self.enable_clock_reference_variation:
            for site_key in self.sites:
                flags = [
                    flag
                    for (flag_site_key, _clock), flag in self.clock_flags.items()
                    if flag_site_key == site_key
                ]
                constraints.extend(self._at_most_one(flags))
        return constraints

    def repair_domain_constraints(self) -> list[z3.BoolRef]:
        constraints: list[z3.BoolRef] = []
        for site_key, site in sorted(self.sites.items()):
            delta = self.delta(site)
            if site_key in self.blocked_sites:
                constraints.append(delta == 0)
            if site.bound is not None:
                constraints.append(delta >= z3.RealVal(-site.bound))
            if self.max_bound_delta is not None:
                constraints.append(delta >= z3.RealVal(-self.max_bound_delta))
                constraints.append(delta <= z3.RealVal(self.max_bound_delta))
        constraints.extend(self.variation_constraints())
        return constraints

    def trace_site_counts(self, trace_indices: list[int]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for trace_index in trace_indices:
            seen: set[str] = set()
            trace = self.traces[trace_index]
            node_ids = [trace.initial_node] + [step.target for step in trace.steps]
            for node_id in node_ids:
                node = trace.nodes.get(node_id)
                if node is None:
                    continue
                for location_id in node.locations:
                    location = trace.locations.get(location_id)
                    if location is None:
                        continue
                    for site in self._constraints_from_text(
                        location.invariant,
                        owner_id=location.id,
                        owner_kind="location",
                        owner_name=location.name,
                        label_kind="invariant",
                    ):
                        seen.add(site.site_key)
            for step in trace.steps:
                for edge_id in step.edge_ids:
                    edge = trace.edges.get(edge_id)
                    if edge is None:
                        continue
                    for site in self._constraints_from_text(
                        edge.guard,
                        owner_id=edge.id,
                        owner_kind="transition",
                        owner_name=edge.owner_name,
                        label_kind="guard",
                    ):
                        seen.add(site.site_key)
            for site_key in seen:
                counts[site_key] = counts.get(site_key, 0) + 1
        return counts

    def site_risk_weight(self, site: ClockConstraint, action: str) -> int:
        risk = 10
        if site.label_kind == "invariant":
            risk += 8
        if site.operator == "==":
            risk += 6
        if action == "operator":
            risk += 10
        elif action == "clock":
            risk += 14
        return risk

    def site_benefit_weight(self, site: ClockConstraint, action: str, site_counts: dict[str, int]) -> int:
        coverage = max(1, site_counts.get(site.site_key, 0))
        benefit = 10 * coverage
        if site.label_kind == "guard":
            benefit += 2
        if action in {"operator", "clock"}:
            benefit += 1
        return benefit

    def trace_obligation_qf(
        self,
        trace_index: int,
        timeout_ms: int | None = None,
    ) -> tuple[z3.BoolRef | None, list[str]]:
        trace = self.traces[trace_index]
        constraints, quantified, state_vars = self.encode_trace_constraints_delay_substituted(
            trace,
            f"dom{trace_index}",
        )
        terminal_index = len(trace.steps) + 1
        property_expr, unsupported = self.property_formula_for_state(
            trace.property_formula,
            trace.terminal_node.locations,
            state_vars[terminal_index],
        )
        if unsupported or property_expr is None:
            return None, [f"P{trace.property_index}: {item}" for item in unsupported]
        obligation = z3.Not(z3.Exists(quantified, z3.And(*(constraints + [z3.Not(property_expr)]))))
        qf = self.quantifier_eliminated_constraints([obligation], timeout_ms=timeout_ms)
        if qf is None:
            return None, [f"QE unavailable for trace {trace_index} path obligation"]
        return z3.And(*qf), []

    def analyze_path_relations(self, dag: PathDAG, max_smt_checks: int = 40) -> PathRelationReport:
        report = PathRelationReport()
        report.common_subpaths = dag.common_subpaths()
        report.clusters = dag.cluster_traces()
        report.cluster_representative_indices = sorted(
            {cluster["representative"] for cluster in report.clusters}
        )

        dominance_pairs: set[tuple[int, int, str]] = set()
        skeleton_groups: dict[tuple[tuple[tuple[str, ...], ...], str], list[int]] = {}
        for trace_index, trace in enumerate(self.traces):
            skeleton_groups.setdefault((dag.skeleton(trace_index), normalize_formula(trace.property_formula)), []).append(
                trace_index
            )
        for group in skeleton_groups.values():
            if len(group) < 2:
                continue
            representative = min(group)
            for trace_index in group:
                if trace_index != representative:
                    dominance_pairs.add((representative, trace_index, "identical_skeleton_and_formula"))

        obligations: dict[int, z3.BoolRef] = {}
        unavailable: list[str] = []
        for trace_index in range(len(self.traces)):
            obligation, notes = self.trace_obligation_qf(trace_index)
            if obligation is None:
                unavailable.extend(notes)
                continue
            obligations[trace_index] = obligation
        if unavailable:
            report.notes.extend(unavailable[:8])
            if len(unavailable) > 8:
                report.notes.append(f"{len(unavailable) - 8} additional dominance-precheck note(s) omitted")

        checked = 0
        sorted_indices = sorted(obligations)
        for left in sorted_indices:
            for right in sorted_indices:
                if left == right:
                    continue
                if checked >= max_smt_checks:
                    break
                if any(pair_left == left and pair_right == right for pair_left, pair_right, _method in dominance_pairs):
                    continue
                solver = z3.Solver()
                solver.set(timeout=1200)
                solver.add(*self.repair_domain_constraints())
                solver.add(obligations[left])
                solver.add(z3.Not(obligations[right]))
                checked += 1
                try:
                    check = solver.check()
                except z3.Z3Exception:
                    check = z3.unknown
                if check == z3.unsat:
                    dominance_pairs.add((left, right, "smt_obligation_implication"))
            if checked >= max_smt_checks:
                break
        if len(sorted_indices) * max(0, len(sorted_indices) - 1) > checked:
            report.notes.append(
                f"path dominance SMT checks capped at {checked}/{len(sorted_indices) * (len(sorted_indices) - 1)} pair(s)"
            )

        pair_lookup = {(left, right) for left, right, _method in dominance_pairs}
        dominated: set[int] = set()
        for left, right, _method in dominance_pairs:
            if (right, left) in pair_lookup and right < left:
                continue
            dominated.add(right)

        report.dominance_pairs = [
            {"dominator": left, "dominated": right, "method": method}
            for left, right, method in sorted(dominance_pairs, key=lambda item: (item[1], item[0], item[2]))
        ]
        report.dominated_trace_indices = sorted(dominated)
        report.encoded_trace_indices = [
            index for index in range(len(self.traces)) if index not in dominated
        ]
        if not report.encoded_trace_indices:
            report.encoded_trace_indices = list(range(len(self.traces)))
            report.notes.append("dominance pruning would remove all traces; kept all traces")
        if report.clusters:
            report.notes.append(
                "path clusters choose representatives for reporting; only SMT-proved dominance prunes obligations"
            )
        return report

    def solve(self) -> SymbolicRepairResult:
        start = time.time()
        result = SymbolicRepairResult(status="unknown")
        dag = PathDAG(self.traces, use_dbm_constraints=self.use_dbm_constraints)
        path_relations = self.analyze_path_relations(dag)
        selected_trace_indices = path_relations.encoded_trace_indices or list(range(len(self.traces)))
        result.path_relations = path_relations.to_dict()
        dag_stats = dag.stats().to_dict()
        result.trace_paths = [trace.path for trace in self.traces]

        feasibility_blocks = []
        universal_blocks = []
        universal_vars: list[z3.ExprRef] = []

        for trace_index in selected_trace_indices:
            trace = self.traces[trace_index]
            constraints, _, state_vars = self.encode_trace_constraints_delay_substituted(
                trace,
                f"e{trace_index}",
            )
            feasibility_blocks.extend(constraints)
            terminal_index = len(trace.steps) + 1
            active_locations = trace.terminal_node.locations
            property_expr, unsupported = self.property_formula_for_state(
                trace.property_formula,
                active_locations,
                state_vars[terminal_index],
            )
            if unsupported or property_expr is None:
                result.unsupported.extend([f"P{trace.property_index}: {item}" for item in unsupported])
                result.status = "unsupported"
                result.elapsed_sec = round(time.time() - start, 3)
                return result

        universal_encoding = "tartar_delay_substitution_per_trace"
        if not dag.sharing_safe:
            path_relations.notes.append(
                "Path-DAG sharing disabled because shared prefixes/edges had incompatible semantics; "
                f"prefix_conflicts={len(dag.prefix_conflicts)}, edge_conflicts={len(dag.edge_conflicts)}"
            )
        else:
            path_relations.notes.append(
                "Path-DAG statistics are reported, but universal QE uses TarTar-style per-trace delay substitution "
                "so only delay variables are quantified."
            )
        dag_vars, dag_universal_blocks, dag_encoding_stats, dag_notes = self.encode_per_trace_universal_obligations(
            selected_trace_indices,
            "uTrace",
        )
        unsupported_notes = [note for note in dag_notes if note.startswith("P")]
        if unsupported_notes:
            result.unsupported.extend(unsupported_notes)
            result.status = "unsupported"
            result.elapsed_sec = round(time.time() - start, 3)
            return result
        path_relations.notes.extend(note for note in dag_notes if not note.startswith("P"))
        result.path_relations = path_relations.to_dict()
        universal_vars.extend(dag_vars)
        universal_blocks.extend(dag_universal_blocks)
        independent_node_count = sum(len(self.traces[index].steps) + 2 for index in selected_trace_indices)
        independent_edge_count = sum(len(self.traces[index].steps) for index in selected_trace_indices)
        dag_stats.update(
            {
                "independent_universal_node_count": independent_node_count,
                "independent_universal_edge_count": independent_edge_count,
                "encoded_universal_node_count": dag_encoding_stats["encoded_node_count"],
                "encoded_universal_edge_count": dag_encoding_stats["encoded_edge_count"],
                "saved_universal_nodes": max(0, independent_node_count - dag_encoding_stats["encoded_node_count"]),
                "saved_universal_edges": max(0, independent_edge_count - dag_encoding_stats["encoded_edge_count"]),
                "terminal_observation_count": dag_encoding_stats["terminal_observation_count"],
                "quantified_variable_count": dag_encoding_stats["quantified_variable_count"],
                "encoded_trace_count": dag_encoding_stats["encoded_trace_count"],
                "universal_encoding": universal_encoding,
                "feasibility_encoding": "tartar_delay_substitution_existential_selected",
                "prefix_conflict_count": len(dag.prefix_conflicts),
                "edge_conflict_count": len(dag.edge_conflicts),
            }
        )
        result.dag = dag_stats

        hard_constraints: list[z3.BoolRef] = list(feasibility_blocks)
        hard_constraints.extend(self.variation_constraints())

        abs_vars: list[z3.IntNumRef] = []
        changed_flags: list[z3.BoolRef] = []
        default_soft_constraints: list[z3.BoolRef] = []
        magnitude_terms: list[z3.ArithRef] = []
        risk_terms: list[z3.ArithRef] = []
        benefit_terms: list[z3.ArithRef] = []
        objective_site_weights: dict[str, dict] = {}
        delta_constraints: list[z3.BoolRef] = []
        site_counts = self.trace_site_counts(selected_trace_indices)
        for site_key, site in sorted(self.sites.items()):
            delta = self.delta(site)
            if site_key in self.blocked_sites:
                delta_constraints.append(delta == 0)
            if site.bound is not None:
                delta_constraints.append(delta >= z3.RealVal(-site.bound))
            if self.max_bound_delta is not None:
                delta_constraints.append(delta >= z3.RealVal(-self.max_bound_delta))
                delta_constraints.append(delta <= z3.RealVal(self.max_bound_delta))
            changed = delta != 0
            changed_flags.append(changed)
            default_soft_constraints.append(delta == 0)
            abs_delta = z3.Real(f"abs__{re.sub(r'[^A-Za-z0-9_]', '_', site_key)}")
            delta_constraints.append(abs_delta >= delta)
            delta_constraints.append(abs_delta >= -delta)
            delta_constraints.append(abs_delta >= 0)
            abs_vars.append(abs_delta)
            magnitude_terms.append(abs_delta)
            risk = self.site_risk_weight(site, "bound")
            benefit = self.site_benefit_weight(site, "bound", site_counts)
            risk_terms.append(z3.If(changed, z3.IntVal(risk), z3.IntVal(0)))
            benefit_terms.append(z3.If(changed, z3.IntVal(benefit), z3.IntVal(0)))
            objective_site_weights[site_key] = {
                "owner_kind": site.owner_kind,
                "owner_name": site.owner_name,
                "label_kind": site.label_kind,
                "clock": site.clock,
                "operator": site.operator,
                "trace_coverage": site_counts.get(site_key, 0),
                "bound_risk": risk,
                "bound_benefit": benefit,
            }
        for blocked in self.blocked_assignments:
            exact_terms = [
                self.delta(site) == _z3_number(blocked.get(site_key, 0))
                for site_key, site in sorted(self.sites.items())
            ]
            if exact_terms:
                delta_constraints.append(z3.Not(z3.And(*exact_terms)))
        for _key, flag in sorted(self.operator_flags.items()):
            changed_flags.append(flag)
            default_soft_constraints.append(z3.Not(flag))
            magnitude_terms.append(z3.If(flag, z3.IntVal(1), z3.IntVal(0)))
            site = self.sites[_key[0]]
            risk = self.site_risk_weight(site, "operator")
            benefit = self.site_benefit_weight(site, "operator", site_counts)
            risk_terms.append(z3.If(flag, z3.IntVal(risk), z3.IntVal(0)))
            benefit_terms.append(z3.If(flag, z3.IntVal(benefit), z3.IntVal(0)))
        for _key, flag in sorted(self.clock_flags.items()):
            changed_flags.append(flag)
            default_soft_constraints.append(z3.Not(flag))
            magnitude_terms.append(z3.If(flag, z3.IntVal(1), z3.IntVal(0)))
            site = self.sites[_key[0]]
            risk = self.site_risk_weight(site, "clock")
            benefit = self.site_benefit_weight(site, "clock", site_counts)
            risk_terms.append(z3.If(flag, z3.IntVal(risk), z3.IntVal(0)))
            benefit_terms.append(z3.If(flag, z3.IntVal(benefit), z3.IntVal(0)))

        def optimize_model(base_constraints: list[z3.BoolRef]) -> tuple[z3.CheckSatResult, z3.ModelRef | None]:
            optimizer = z3.Optimize()
            optimizer.set(priority="lex")
            optimizer.add(*base_constraints)
            optimizer.add(*delta_constraints)
            for default_constraint in default_soft_constraints:
                optimizer.add_soft(default_constraint, weight=1, id="changed_repairs")
            if magnitude_terms:
                optimizer.minimize(z3.Sum(magnitude_terms))
            if risk_terms:
                optimizer.minimize(z3.Sum(risk_terms))
            if benefit_terms:
                optimizer.maximize(z3.Sum(benefit_terms))
            optimize_check = optimizer.check()
            if optimize_check == z3.sat:
                return optimize_check, optimizer.model()
            return optimize_check, None

        model = None
        check = z3.unknown
        solver_kind = "z3_optimize_maxsmt_qe"
        qf_universal_constraints: list[z3.BoolRef] = []
        if universal_blocks:
            qf_universal_constraints = self.quantifier_eliminated_constraints(universal_blocks)
            if qf_universal_constraints is None:
                result.elapsed_sec = round(time.time() - start, 3)
                result.status = "unknown"
                result.objective = {
                    "solver": solver_kind,
                    "qe_status": "failed_or_left_quantifiers",
                    "objective_scope": "qe_required_before_optimize",
                }
                return result
        base_constraints = list(hard_constraints) + list(qf_universal_constraints)
        check, model = optimize_model(base_constraints)

        result.elapsed_sec = round(time.time() - start, 3)
        if model is None:
            result.status = "unsat" if check == z3.unsat else "unknown"
            return result
        changes: list[SymbolicRepairChange] = []
        for site_key, site in sorted(self.sites.items()):
            delta_value = model.eval(self.delta(site), model_completion=True)
            delta_fraction = _z3_numeric_to_fraction(delta_value)
            if delta_fraction is None:
                continue
            if delta_fraction == 0:
                continue
            template = site.owner_id.split(".", 1)[0] if "." in site.owner_id else ""
            old_bound = site.bound if site.bound is not None else 0
            new_bound_fraction = Fraction(old_bound, 1) + delta_fraction
            delta_number = _fraction_to_number(delta_fraction)
            new_bound_number = _fraction_to_number(new_bound_fraction)
            changes.append(
                SymbolicRepairChange(
                    action="bound",
                    owner_kind=site.owner_kind,
                    owner_name=site.owner_name,
                    template=template,
                    label_kind=site.label_kind,
                    clock=site.clock,
                    operator=site.operator,
                    old_bound=old_bound,
                    new_bound=new_bound_number,
                    site_key=site_key,
                    delta=delta_number,
                )
            )
        for (site_key, operator), flag in sorted(self.operator_flags.items()):
            if not z3.is_true(model.eval(flag, model_completion=True)):
                continue
            site = self.sites[site_key]
            template = site.owner_id.split(".", 1)[0] if "." in site.owner_id else ""
            old_bound = site.bound if site.bound is not None else 0
            changes.append(
                SymbolicRepairChange(
                    action="operator",
                    owner_kind=site.owner_kind,
                    owner_name=site.owner_name,
                    template=template,
                    label_kind=site.label_kind,
                    clock=site.clock,
                    operator=site.operator,
                    old_bound=old_bound,
                    new_bound=old_bound,
                    site_key=f"{site_key}:operator:{operator}",
                    delta=0,
                    new_operator=operator,
                )
            )
        for (site_key, clock), flag in sorted(self.clock_flags.items()):
            if not z3.is_true(model.eval(flag, model_completion=True)):
                continue
            site = self.sites[site_key]
            template = site.owner_id.split(".", 1)[0] if "." in site.owner_id else ""
            old_bound = site.bound if site.bound is not None else 0
            changes.append(
                SymbolicRepairChange(
                    action="clock",
                    owner_kind=site.owner_kind,
                    owner_name=site.owner_name,
                    template=template,
                    label_kind=site.label_kind,
                    clock=site.clock,
                    operator=site.operator,
                    old_bound=old_bound,
                    new_bound=old_bound,
                    site_key=f"{site_key}:clock:{clock}",
                    delta=0,
                    new_clock=clock,
                )
            )

        def eval_int_sum(terms: list[z3.ArithRef]) -> int:
            if not terms:
                return 0
            value = model.eval(z3.Sum(terms), model_completion=True)
            if hasattr(value, "as_long"):
                return value.as_long()
            return 0

        result.status = "repaired" if changes else "no_change"
        result.changes = changes
        result.objective = {
            "solver": solver_kind,
            "objectives": [
                "minimize_changed_repairs",
                "minimize_total_magnitude",
                "minimize_symbolic_risk",
                "maximize_trace_coverage_benefit",
            ],
            "objective_scope": (
                "unified_z3_optimize"
                if solver_kind == "z3_optimize_maxsmt_qe"
                else "qe_required_before_optimize"
            ),
            "max_bound_delta": self.max_bound_delta,
            "blocked_symbolic_assignments": len(self.blocked_assignments),
            "changed_repairs": len(changes),
            "changed_bounds": sum(1 for change in changes if change.action == "bound"),
            "changed_operators": sum(1 for change in changes if change.action == "operator"),
            "changed_clock_references": sum(1 for change in changes if change.action == "clock"),
            "total_magnitude": sum(abs(float(c.new_bound) - float(c.old_bound)) if c.action == "bound" else 1 for c in changes),
            "symbolic_risk": eval_int_sum(risk_terms),
            "trace_coverage_benefit": eval_int_sum(benefit_terms),
            "site_weights": objective_site_weights,
        }
        return result


def solve_symbolic_repair(
    trace_paths: list[Path],
    properties_by_index: dict[int, str],
    max_bound_delta: int | None = None,
    model_path: Path | None = None,
    enable_operator_variation: bool = False,
    enable_clock_reference_variation: bool = False,
    use_dbm_constraints: bool = False,
    blocked_assignments: list[dict[str, int | float]] | None = None,
    blocked_sites: set[str] | None = None,
    qe_timeout_ms: int = 500_000,
) -> SymbolicRepairResult:
    traces: list[TimedDiagnosticTrace] = []
    unsupported: list[str] = []
    urgent_locations = load_urgent_locations(model_path) if model_path is not None else set()
    bound_constants, model_clocks, model_variable_types = load_model_bound_environment(model_path)
    for path in trace_paths:
        match = re.search(r"property_(\d+)_trace", path.name)
        property_index = int(match.group(1)) if match else 1
        formula = properties_by_index.get(property_index)
        if formula is None:
            unsupported.append(f"missing formula for trace {path}")
            continue
        traces.append(parse_verifyta_trace(path, property_index, formula, urgent_locations))
    if unsupported:
        return SymbolicRepairResult(status="unsupported", unsupported=unsupported, trace_paths=[str(path) for path in trace_paths])
    if not traces:
        return SymbolicRepairResult(status="no_traces")
    encoder = TDTEncoder(
        traces,
        max_bound_delta=max_bound_delta,
        enable_operator_variation=enable_operator_variation,
        enable_clock_reference_variation=enable_clock_reference_variation,
        use_dbm_constraints=use_dbm_constraints,
        blocked_assignments=blocked_assignments,
        blocked_sites=blocked_sites,
        bound_constants=bound_constants,
        model_clocks=model_clocks,
        model_variable_types=model_variable_types,
        qe_timeout_ms=qe_timeout_ms,
    )
    return encoder.solve()


