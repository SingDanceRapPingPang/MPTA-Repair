"""Formula-level property relation checks for UPPAAL safety queries.

The analyzer intentionally supports the property fragment used by the current
datasets and by the TARTAR DB example: Boolean combinations of location
predicates and simple clock/integer comparisons under an ``A[]`` safety
wrapper.  Unsupported formulas are reported explicitly instead of guessed.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

import z3


INSTANCE_NAME_RE = r"[A-Za-z_]\w*(?:\(\d+\))?"
LOCATION_RE = re.compile(rf"\b(?P<template>{INSTANCE_NAME_RE})\.(?P<location>[A-Za-z_]\w*)\b")
IDENT_ATOM = rf"{INSTANCE_NAME_RE}(?:\.[A-Za-z_]\w*)?"
COMPARISON_RE = re.compile(
    rf"(?<![\w.])(?P<left>{IDENT_ATOM})\s*(?P<op><=|>=|==|!=|<|>)\s*(?P<right>-?\d+|{IDENT_ATOM})\b"
)
IDENT_RE = re.compile(r"\b[A-Za-z_]\w*\b")


@dataclass
class ParsedFormula:
    raw: str
    normalized: str
    unsupported: list[str] = field(default_factory=list)
    locations: set[str] = field(default_factory=set)
    identifiers: set[str] = field(default_factory=set)


@dataclass
class PropertyRelationReport:
    equivalent_groups: list[list[int]]
    implications: list[dict]
    conflicts: list[dict]
    unsupported: dict[int, list[str]]

    def to_dict(self) -> dict:
        return asdict(self)


def strip_safety_wrapper(formula: str) -> str:
    text = formula.strip().rstrip(";")
    if text.startswith("A[]"):
        text = text[3:].strip()
    return text


def normalize_formula(formula: str) -> str:
    text = strip_safety_wrapper(formula)
    text = text.replace("&&", " and ").replace("||", " or ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _z3_name(kind: str, name: str) -> str:
    return f"{kind}__{re.sub(r'[^A-Za-z0-9_]', '_', name)}"


def _arith_expr(text: str, clocks: set[str], constants: dict[str, int]) -> z3.ArithRef | None:
    expr = text.strip()
    parts = re.split(r"(\+|-)", expr)
    if not parts:
        return None

    def atom(value: str) -> z3.ArithRef | None:
        value = value.strip()
        if re.fullmatch(r"-?\d+", value):
            return z3.RealVal(int(value))
        if value in constants:
            return z3.RealVal(constants[value])
        if value in clocks or value.split(".")[-1] in clocks:
            return z3.Real(_z3_name("clock", value))
        if re.fullmatch(IDENT_ATOM, value):
            return z3.Real(_z3_name("var", value))
        return None

    current = atom(parts[0])
    if current is None:
        return None
    index = 1
    while index < len(parts):
        op = parts[index]
        right = atom(parts[index + 1])
        if right is None:
            return None
        current = current + right if op == "+" else current - right
        index += 2
    return current


def _comparison_expr(match: re.Match[str], clocks: set[str], constants: dict[str, int]) -> z3.BoolRef | None:
    op = match.group("op")
    left_expr = _arith_expr(match.group("left"), clocks, constants)
    right_expr = _arith_expr(match.group("right"), clocks, constants)
    if left_expr is None or right_expr is None:
        return None
    if op == "<=":
        return left_expr <= right_expr
    if op == "<":
        return left_expr < right_expr
    if op == ">=":
        return left_expr >= right_expr
    if op == ">":
        return left_expr > right_expr
    if op == "==":
        return left_expr == right_expr
    if op == "!=":
        return left_expr != right_expr
    return None


def parse_formula_to_z3(
    formula: str,
    clocks: set[str],
    constants: dict[str, int] | None = None,
) -> tuple[ParsedFormula, z3.BoolRef | None]:
    constants = constants or {}
    normalized = normalize_formula(formula)
    parsed = ParsedFormula(
        raw=formula,
        normalized=normalized,
        identifiers=set(IDENT_RE.findall(normalized)),
    )
    env: dict[str, z3.ExprRef] = {}
    expr_text = normalized

    replacements: list[tuple[int, int, str]] = []
    arith_side = rf"(?:{IDENT_ATOM}|-?\d+)(?:\s*[+\-]\s*(?:{IDENT_ATOM}|-?\d+))*"
    comparison_re = re.compile(
        rf"(?<![\w.])(?P<left>{arith_side})\s*(?P<op><=|>=|==|!=|<|>)\s*(?P<right>{arith_side})(?![\w.])"
    )
    for match in comparison_re.finditer(expr_text):
        comparison = _comparison_expr(match, clocks, constants)
        if comparison is None:
            parsed.unsupported.append(match.group(0))
            continue
        symbol = _z3_name("cmp", f"{match.start()}_{match.end()}")
        env[symbol] = comparison
        replacements.append((match.start(), match.end(), symbol))
    for start, end, symbol in reversed(replacements):
        expr_text = expr_text[:start] + symbol + expr_text[end:]

    parsed.locations = {f"{m.group('template')}.{m.group('location')}" for m in LOCATION_RE.finditer(expr_text)}
    for location in sorted(parsed.locations, key=len, reverse=True):
        symbol = _z3_name("loc", location)
        env[symbol] = z3.Bool(symbol)
        expr_text = re.sub(rf"\b{re.escape(location)}\b", symbol, expr_text)

    # Convert a shallow Boolean expression by repeatedly replacing binary
    # operators. This keeps the supported fragment explicit and avoids eval on
    # arbitrary source text.
    try:
        z3_expr = _parse_boolean_expr(expr_text, env)
    except ValueError as exc:
        parsed.unsupported.append(str(exc))
        return parsed, None
    return parsed, z3_expr


def _strip_outer_parens(text: str) -> str:
    text = text.strip()
    while text.startswith("(") and text.endswith(")"):
        depth = 0
        balanced = True
        for index, char in enumerate(text):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0 and index != len(text) - 1:
                    balanced = False
                    break
        if not balanced:
            break
        text = text[1:-1].strip()
    return text


def _split_top_level(text: str, operator: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    i = 0
    token = f" {operator} "
    while i < len(text):
        char = text[i]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif depth == 0 and text.startswith(token, i):
            parts.append(text[start:i].strip())
            i += len(token)
            start = i
            continue
        i += 1
    if parts:
        parts.append(text[start:].strip())
    return parts


def _parse_boolean_expr(text: str, env: dict[str, z3.ExprRef]) -> z3.BoolRef:
    text = _strip_outer_parens(text)
    parts = _split_top_level(text, "imply")
    if parts:
        if len(parts) != 2:
            raise ValueError(f"unsupported chained implication: {text}")
        return z3.Implies(_parse_boolean_expr(parts[0], env), _parse_boolean_expr(parts[1], env))
    for operator, constructor in [("or", z3.Or), ("and", z3.And)]:
        parts = _split_top_level(text, operator)
        if parts:
            return constructor(*[_parse_boolean_expr(part, env) for part in parts])
    if text.startswith("not "):
        return z3.Not(_parse_boolean_expr(text[4:], env))
    if text.startswith("z3.Not"):
        inner = text[len("z3.Not") :].strip()
        return z3.Not(_parse_boolean_expr(inner, env))
    if text in {"true", "True", "1"}:
        return z3.BoolVal(True)
    if text in {"false", "False", "0"}:
        return z3.BoolVal(False)
    if text in env:
        value = env[text]
        if not z3.is_bool(value):
            raise ValueError(f"non-Boolean atom {text}")
        return value
    raise ValueError(f"unsupported Boolean fragment: {text}")


def _unsat(expr: z3.BoolRef) -> bool:
    solver = z3.Solver()
    solver.add(expr)
    return solver.check() == z3.unsat


def implies(left: z3.BoolRef, right: z3.BoolRef) -> bool:
    return _unsat(z3.And(left, z3.Not(right)))


def analyze_property_relations(
    formulas: list[str],
    clocks: set[str],
    constants: dict[str, int] | None = None,
) -> PropertyRelationReport:
    parsed: dict[int, ParsedFormula] = {}
    exprs: dict[int, z3.BoolRef] = {}
    unsupported: dict[int, list[str]] = {}
    for index, formula in enumerate(formulas, 1):
        parsed_formula, expr = parse_formula_to_z3(formula, clocks, constants)
        parsed[index] = parsed_formula
        if parsed_formula.unsupported or expr is None:
            unsupported[index] = parsed_formula.unsupported or ["unsupported formula"]
        else:
            exprs[index] = expr

    implications: list[dict] = []
    equivalent_pairs: set[tuple[int, int]] = set()
    conflicts: list[dict] = []
    for left_index, left_expr in exprs.items():
        for right_index, right_expr in exprs.items():
            if left_index == right_index:
                continue
            if implies(left_expr, right_expr):
                implications.append({"stronger": left_index, "weaker": right_index})
                if implies(right_expr, left_expr):
                    equivalent_pairs.add(tuple(sorted((left_index, right_index))))
        for right_index, right_expr in exprs.items():
            if left_index >= right_index:
                continue
            if _unsat(z3.And(left_expr, right_expr)):
                conflicts.append({"properties": [left_index, right_index], "reason": "formula conjunction is unsat"})

    parent = {index: index for index in exprs}

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    for left, right in equivalent_pairs:
        parent[find(right)] = find(left)
    groups: dict[int, list[int]] = {}
    for index in exprs:
        groups.setdefault(find(index), []).append(index)
    equivalent_groups = [sorted(group) for group in groups.values() if len(group) > 1]

    deduped_implications = []
    seen = set()
    for item in implications:
        key = (item["stronger"], item["weaker"])
        if key not in seen:
            seen.add(key)
            deduped_implications.append(item)
    return PropertyRelationReport(
        equivalent_groups=equivalent_groups,
        implications=deduped_implications,
        conflicts=conflicts,
        unsupported=unsupported,
    )
