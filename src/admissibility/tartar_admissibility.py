"""TARTAR-style admissibility checking for UPPAAL timed automata.

This module follows the implementation of TARTAR's
``tartar.job_admissibility`` module:

1. call ``opaal/createTS.sh`` for both UPPAAL models;
2. parse the generated XML transition systems;
3. build NFAs over transition labels;
4. determinize conceptually and search for an untimed language difference.

The expensive timed-state-space construction is intentionally delegated to the
original opaal/LTSmin pipeline.  The in-process equivalence checker mirrors the
AutomataLib logic used by TARTAR and also exposes the shortest separating word
when the two transition systems are not equivalent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET


DEFAULT_TARTAR_ROOT = Path(__file__).resolve().parents[2] / "TarTar-master"
TEXT_TAIL_LIMIT = 8000


@dataclass
class AdmissibilityConfig:
    """Configuration for a TARTAR-compatible admissibility run."""

    tartar_root: Path = DEFAULT_TARTAR_ROOT
    output_dir: Path = Path("experiments/admissibility")
    runner: str = "auto"
    timeout: int = 3600
    keep_transition_systems: bool = True
    verbose: bool = False


@dataclass
class EnvironmentReport:
    ok: bool
    runner: str | None
    tartar_root: str
    opaal_dir: str
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CommandRecord:
    command: str
    cwd: str
    returncode: int | None
    elapsed_sec: float
    stdout_path: str | None = None
    stderr_path: str | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TransitionSystem:
    states: list[str]
    initial_states: frozenset[str]
    alphabet: list[str]
    transitions: dict[str, dict[str, frozenset[str]]]


@dataclass
class EquivalenceResult:
    equivalent: bool
    counterexample: list[str]
    state_count_1: int
    state_count_2: int
    transition_count_1: int
    transition_count_2: int
    alphabet: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AdmissibilityResult:
    status: str
    admissible: bool | None
    model_before: str
    model_after: str
    output_dir: str
    environment: dict
    elapsed_sec: float
    transition_system_1: str | None = None
    transition_system_2: str | None = None
    counterexample: list[str] = field(default_factory=list)
    commands: list[dict] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class AdmissibilityError(RuntimeError):
    """Raised when the TARTAR-style admissibility pipeline cannot complete."""


def _tail(text: str, limit: int = TEXT_TAIL_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def _brief_process_output(text: str, limit: int = 1000) -> str:
    if not text:
        return ""
    if "\x00" in text:
        text = text.replace("\x00", "")
    text = "".join(ch if ch in "\n\r\t" or ord(ch) >= 32 else " " for ch in text)
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _write_json(path: Path, data: dict) -> None:
    _write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def _strip_namespace(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _stable_name(prefix: str, path: Path) -> str:
    digest = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{path.stem}_{digest}.xml"


def _windows_path_to_wsl(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    rest = resolved.as_posix()
    if drive:
        rest = rest.split(":", 1)[1]
        return f"/mnt/{drive}{rest}"
    return resolved.as_posix()


def _opaal_dir(config: AdmissibilityConfig) -> Path:
    return (config.tartar_root / "opaal").resolve()


def _native_env(config: AdmissibilityConfig) -> dict[str, str]:
    tartar_root = config.tartar_root.resolve()
    opaal_dir = tartar_root / "opaal"
    pyuppaal_dir = tartar_root / "pyuppaal"
    ltsmin_dir = tartar_root / "ltsmin-3.0.2" / "src" / "pins2lts-mc"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        str(path)
        for path in [opaal_dir, pyuppaal_dir]
        if path.exists()
    ) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PATH"] = os.pathsep.join(
        str(path)
        for path in [ltsmin_dir, opaal_dir / "bin"]
        if path.exists()
    ) + os.pathsep + env.get("PATH", "")
    return env


def _native_environment_messages(config: AdmissibilityConfig) -> tuple[bool, list[str]]:
    messages: list[str] = []
    opaal_dir = _opaal_dir(config)
    env = _native_env(config)
    python = shutil.which("python", path=env.get("PATH"))
    python2_ok = False
    if python:
        try:
            proc = subprocess.run(
                [
                    python,
                    "-c",
                    "import sys; raise SystemExit(0 if sys.version_info[0] == 2 else 1)",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            python2_ok = proc.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            python2_ok = False
    checks = [
        (opaal_dir.exists(), f"opaal directory not found: {opaal_dir}"),
        ((opaal_dir / "createTS.sh").exists(), f"createTS.sh not found: {opaal_dir / 'createTS.sh'}"),
        ((opaal_dir / "bin" / "opaal_ltsmin").exists(), f"opaal_ltsmin not found: {opaal_dir / 'bin' / 'opaal_ltsmin'}"),
        (shutil.which("bash") is not None, "bash is not available"),
        (python2_ok, "python command is missing or is not Python 2.x; opaal_ltsmin uses Python 2 syntax"),
        (shutil.which("g++") is not None, "g++ is not available"),
        (shutil.which("bc") is not None, "bc is not available"),
        (shutil.which("opaal2lts-mc", path=env.get("PATH")) is not None, "opaal2lts-mc is not available in PATH"),
        (Path("/usr/local/uppaal/include").exists(), "UPPAAL include directory is missing: /usr/local/uppaal/include"),
        (Path("/usr/local/uppaal/lib").exists(), "UPPAAL library directory is missing: /usr/local/uppaal/lib"),
    ]
    for ok, message in checks:
        if not ok:
            messages.append(message)
    return not messages, messages


def _wsl_probe(config: AdmissibilityConfig) -> tuple[bool, list[str]]:
    messages: list[str] = []
    if shutil.which("wsl.exe") is None and shutil.which("wsl") is None:
        return False, ["wsl.exe is not available"]

    opaal_dir = _windows_path_to_wsl(_opaal_dir(config))
    tartar_root = _windows_path_to_wsl(config.tartar_root)
    checks = [
        ("command -v bash >/dev/null", "bash is not available in WSL"),
        (
            "command -v python >/dev/null && "
            "python -c 'import sys; raise SystemExit(0 if sys.version_info[0] == 2 else 1)'",
            "python command is missing or is not Python 2.x in WSL; opaal_ltsmin uses Python 2 syntax",
        ),
        ("command -v g++ >/dev/null", "g++ is not available in WSL"),
        ("command -v bc >/dev/null", "bc is not available in WSL"),
        (f"test -d {shlex.quote(tartar_root)}", f"tartar root is not accessible in WSL: {tartar_root}"),
        (f"test -f {shlex.quote(opaal_dir + '/createTS.sh')}", f"createTS.sh not found in WSL: {opaal_dir}/createTS.sh"),
        (
            f"test -f {shlex.quote(opaal_dir + '/bin/opaal_ltsmin')}",
            f"opaal_ltsmin not found in WSL: {opaal_dir}/bin/opaal_ltsmin",
        ),
        (
            "command -v opaal2lts-mc >/dev/null || "
            f"test -x {shlex.quote(tartar_root + '/ltsmin-3.0.2/src/pins2lts-mc/opaal2lts-mc')}",
            "opaal2lts-mc is not available in WSL PATH or TARTAR ltsmin build output",
        ),
        ("test -d /usr/local/uppaal/include", "UPPAAL include directory is missing in WSL: /usr/local/uppaal/include"),
        ("test -d /usr/local/uppaal/lib", "UPPAAL library directory is missing in WSL: /usr/local/uppaal/lib"),
    ]
    script_lines = ["missing=0"]
    for command, message in checks:
        script_lines.append(f"{command} || {{ printf '%s\\n' {shlex.quote('MISSING: ' + message)}; missing=1; }}")
    script_lines.append("exit $missing")
    script = "\n".join(script_lines)
    proc = subprocess.run(
        ["wsl.exe", "-e", "bash", "-lc", script],
        cwd=str(config.tartar_root.resolve().parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    if proc.returncode == 0:
        return True, []
    messages.append("WSL/opaal dependency probe failed")
    missing_messages = [
        line.removeprefix("MISSING: ").strip()
        for line in _brief_process_output(proc.stdout or "", limit=4000).splitlines()
        if line.startswith("MISSING: ")
    ]
    if missing_messages:
        messages.extend(missing_messages)
    else:
        detail = _brief_process_output(proc.stderr or proc.stdout or "")
        messages.append(detail)
    return False, messages


def check_environment(config: AdmissibilityConfig | None = None) -> EnvironmentReport:
    """Check whether the original opaal/LTSmin pipeline can run."""

    config = config or AdmissibilityConfig()
    config.tartar_root = config.tartar_root.resolve()
    config.output_dir = config.output_dir.resolve()
    opaal_dir = _opaal_dir(config)
    runner = config.runner.lower()
    if runner not in {"auto", "native", "wsl"}:
        return EnvironmentReport(
            ok=False,
            runner=None,
            tartar_root=str(config.tartar_root),
            opaal_dir=str(opaal_dir),
            messages=[f"unknown runner: {config.runner}"],
        )

    if runner == "native" and platform.system().lower() == "windows":
        return EnvironmentReport(
            ok=False,
            runner="native",
            tartar_root=str(config.tartar_root),
            opaal_dir=str(opaal_dir),
            messages=["native opaal is Linux-oriented; use WSL or run on Linux"],
        )

    if runner in {"auto", "native"} and platform.system().lower() != "windows":
        ok, messages = _native_environment_messages(config)
        if ok:
            return EnvironmentReport(True, "native", str(config.tartar_root), str(opaal_dir), [])
        if runner == "native":
            return EnvironmentReport(False, "native", str(config.tartar_root), str(opaal_dir), messages)

    if runner in {"auto", "wsl"}:
        ok, messages = _wsl_probe(config)
        if ok:
            return EnvironmentReport(True, "wsl", str(config.tartar_root), str(opaal_dir), [])
        if runner == "wsl":
            return EnvironmentReport(False, "wsl", str(config.tartar_root), str(opaal_dir), messages)

    messages: list[str] = []
    if platform.system().lower() == "windows":
        messages.append("native opaal is Linux-oriented; use WSL or run on Linux")
    else:
        _, native_messages = _native_environment_messages(config)
        messages.extend(native_messages)
    _, wsl_messages = _wsl_probe(config)
    messages.extend(wsl_messages)
    return EnvironmentReport(False, None, str(config.tartar_root), str(opaal_dir), messages)


def _run_native_create_ts(
    model_path: Path,
    ts_path: Path,
    config: AdmissibilityConfig,
    stdout_path: Path,
    stderr_path: Path,
) -> CommandRecord:
    opaal_dir = _opaal_dir(config)
    command = ["bash", "createTS.sh", str(model_path), str(ts_path)]
    start = time.time()
    proc = subprocess.run(
        command,
        cwd=opaal_dir,
        env=_native_env(config),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=config.timeout,
    )
    elapsed = round(time.time() - start, 3)
    _write_text(stdout_path, proc.stdout or "")
    _write_text(stderr_path, proc.stderr or "")
    return CommandRecord(
        command=" ".join(shlex.quote(part) for part in command),
        cwd=str(opaal_dir),
        returncode=proc.returncode,
        elapsed_sec=elapsed,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        stdout_tail=_tail(proc.stdout or ""),
        stderr_tail=_tail(proc.stderr or ""),
    )


def _run_wsl_create_ts(
    model_path: Path,
    ts_path: Path,
    config: AdmissibilityConfig,
    stdout_path: Path,
    stderr_path: Path,
) -> CommandRecord:
    tartar_root = _windows_path_to_wsl(config.tartar_root)
    opaal_dir = _windows_path_to_wsl(_opaal_dir(config))
    model_wsl = _windows_path_to_wsl(model_path)
    ts_wsl = _windows_path_to_wsl(ts_path)
    pyuppaal = f"{tartar_root}/pyuppaal"
    ltsmin = f"{tartar_root}/ltsmin-3.0.2/src/pins2lts-mc"
    script = "\n".join(
        [
            "set -e",
            f"cd {shlex.quote(opaal_dir)}",
            f"export PYTHONPATH={shlex.quote(opaal_dir)}:{shlex.quote(pyuppaal)}:${{PYTHONPATH:-}}",
            f"export PATH={shlex.quote(ltsmin)}:{shlex.quote(opaal_dir + '/bin')}:$PATH",
            "chmod +x createTS.sh bin/opaal_ltsmin",
            f"./createTS.sh {shlex.quote(model_wsl)} {shlex.quote(ts_wsl)}",
        ]
    )
    command = ["wsl.exe", "-e", "bash", "-lc", script]
    start = time.time()
    proc = subprocess.run(
        command,
        cwd=str(config.tartar_root.resolve().parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=config.timeout,
    )
    elapsed = round(time.time() - start, 3)
    _write_text(stdout_path, proc.stdout or "")
    _write_text(stderr_path, proc.stderr or "")
    return CommandRecord(
        command="wsl.exe -e bash -lc <createTS>",
        cwd=str(config.tartar_root.resolve().parent),
        returncode=proc.returncode,
        elapsed_sec=elapsed,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        stdout_tail=_tail(proc.stdout or ""),
        stderr_tail=_tail(proc.stderr or ""),
    )


def _create_transition_system(
    model_path: Path,
    ts_path: Path,
    config: AdmissibilityConfig,
    runner: str,
    log_prefix: str,
) -> CommandRecord:
    stdout_path = config.output_dir / f"{log_prefix}.stdout.txt"
    stderr_path = config.output_dir / f"{log_prefix}.stderr.txt"
    if runner == "native":
        command = _run_native_create_ts(model_path, ts_path, config, stdout_path, stderr_path)
    elif runner == "wsl":
        command = _run_wsl_create_ts(model_path, ts_path, config, stdout_path, stderr_path)
    else:
        raise AdmissibilityError(f"unsupported runner: {runner}")
    if command.returncode != 0:
        raise AdmissibilityError(f"createTS failed for {model_path} with exit code {command.returncode}")
    if not ts_path.exists():
        raise AdmissibilityError(f"createTS did not create transition system: {ts_path}")
    return command


def parse_transition_system(path: Path, alphabet_map: dict[str, int] | None = None) -> tuple[TransitionSystem, dict[str, int]]:
    """Parse the XML transition system consumed by TARTAR's AutomatonXMI."""

    alphabet_map = alphabet_map if alphabet_map is not None else {}
    tree = ET.parse(path)
    states: list[str] = []
    state_set: set[str] = set()
    transitions: dict[str, dict[str, set[str]]] = {}

    def add_state(name: str) -> None:
        if name not in state_set:
            state_set.add(name)
            states.append(name)

    for elem in tree.iter():
        tag = _strip_namespace(elem.tag)
        if tag == "state":
            text = "".join(elem.itertext()).strip()
            name = text or elem.get("id") or elem.get("name")
            if name:
                add_state(name)
        elif tag == "edge":
            label = elem.get("label") or ""
            if label not in alphabet_map:
                alphabet_map[label] = len(alphabet_map) + 1

    for elem in tree.iter():
        tag = _strip_namespace(elem.tag)
        if tag != "edge":
            continue
        source = elem.get("from")
        target = elem.get("to")
        label = elem.get("label") or ""
        if not source or not target:
            continue
        add_state(source)
        add_state(target)
        transitions.setdefault(source, {}).setdefault(label, set()).add(target)

    frozen_transitions = {
        source: {label: frozenset(targets) for label, targets in by_label.items()}
        for source, by_label in transitions.items()
    }
    ordered_alphabet = [
        label
        for label, _ in sorted(alphabet_map.items(), key=lambda item: item[1])
    ]
    # TARTAR's AutomatonXMIHandler marks every parsed state as initial and
    # AutomatonXMI marks every NFA state as accepting.  The language therefore
    # consists of all untimed edge-label traces starting from any generated TS
    # state.  We keep that behavior for exact compatibility.
    return (
        TransitionSystem(
            states=states,
            initial_states=frozenset(states),
            alphabet=ordered_alphabet,
            transitions=frozen_transitions,
        ),
        alphabet_map,
    )


def _transition_count(ts: TransitionSystem) -> int:
    return sum(len(targets) for by_label in ts.transitions.values() for targets in by_label.values())


def _next_subset(ts: TransitionSystem, subset: frozenset[str], label: str) -> frozenset[str]:
    result: set[str] = set()
    for state in subset:
        result.update(ts.transitions.get(state, {}).get(label, frozenset()))
    return frozenset(result)


def _accepting(subset: frozenset[str]) -> bool:
    return bool(subset)


def compare_transition_systems(ts_path_1: Path, ts_path_2: Path) -> EquivalenceResult:
    """Compare two opaal/LTSmin XML transition systems as TARTAR does."""

    alphabet_map: dict[str, int] = {}
    ts1, alphabet_map = parse_transition_system(ts_path_1, alphabet_map)
    ts2, alphabet_map = parse_transition_system(ts_path_2, alphabet_map)
    alphabet = [
        label
        for label, _ in sorted(alphabet_map.items(), key=lambda item: item[1])
    ]
    ts1.alphabet[:] = alphabet
    ts2.alphabet[:] = alphabet

    start_pair = (ts1.initial_states, ts2.initial_states)
    queue: deque[tuple[frozenset[str], frozenset[str], list[str]]] = deque()
    queue.append((start_pair[0], start_pair[1], []))
    visited = {start_pair}

    if _accepting(start_pair[0]) != _accepting(start_pair[1]):
        return EquivalenceResult(
            equivalent=False,
            counterexample=[],
            state_count_1=len(ts1.states),
            state_count_2=len(ts2.states),
            transition_count_1=_transition_count(ts1),
            transition_count_2=_transition_count(ts2),
            alphabet=alphabet,
        )

    while queue:
        subset1, subset2, word = queue.popleft()
        for label in alphabet:
            next1 = _next_subset(ts1, subset1, label)
            next2 = _next_subset(ts2, subset2, label)
            next_word = word + [label]
            if _accepting(next1) != _accepting(next2):
                return EquivalenceResult(
                    equivalent=False,
                    counterexample=next_word,
                    state_count_1=len(ts1.states),
                    state_count_2=len(ts2.states),
                    transition_count_1=_transition_count(ts1),
                    transition_count_2=_transition_count(ts2),
                    alphabet=alphabet,
                )
            pair = (next1, next2)
            if pair not in visited:
                visited.add(pair)
                queue.append((next1, next2, next_word))

    return EquivalenceResult(
        equivalent=True,
        counterexample=[],
        state_count_1=len(ts1.states),
        state_count_2=len(ts2.states),
        transition_count_1=_transition_count(ts1),
        transition_count_2=_transition_count(ts2),
        alphabet=alphabet,
    )


def _render_report(result: AdmissibilityResult, equivalence: EquivalenceResult | None = None) -> str:
    lines = [
        "# TARTAR-Style Admissibility Check",
        "",
        "## Result",
        "",
        f"- Status: `{result.status}`",
        f"- Admissible: `{result.admissible}`",
        f"- Model before repair: `{result.model_before}`",
        f"- Model after repair: `{result.model_after}`",
        f"- Elapsed: {result.elapsed_sec} s",
    ]
    if result.error:
        lines.append(f"- Error: `{result.error}`")
    if result.counterexample:
        lines.extend(["", "## Shortest Untimed Separating Trace", ""])
        for index, label in enumerate(result.counterexample, 1):
            lines.append(f"{index}. `{label}`")
    if equivalence:
        lines.extend(
            [
                "",
                "## Transition-System Statistics",
                "",
                f"- TS1 states/transitions: {equivalence.state_count_1}/{equivalence.transition_count_1}",
                f"- TS2 states/transitions: {equivalence.state_count_2}/{equivalence.transition_count_2}",
                f"- Alphabet size: {len(equivalence.alphabet)}",
            ]
        )
    lines.extend(["", "## Environment", ""])
    for message in result.environment.get("messages", []):
        lines.append(f"- {message}")
    if not result.environment.get("messages"):
        lines.append("- Environment probe passed.")
    return "\n".join(lines) + "\n"


def _finalize_result(result: AdmissibilityResult, equivalence: EquivalenceResult | None = None) -> AdmissibilityResult:
    output_dir = Path(result.output_dir)
    _write_json(output_dir / "admissibility_report.json", result.to_dict())
    _write_text(output_dir / "admissibility_report.md", _render_report(result, equivalence))
    return result


def check_admissibility(
    model_before: Path,
    model_after: Path,
    config: AdmissibilityConfig | None = None,
) -> AdmissibilityResult:
    """Check if two UPPAAL models are functionally equivalent after repair."""

    start = time.time()
    config = config or AdmissibilityConfig()
    config.tartar_root = config.tartar_root.resolve()
    config.output_dir = config.output_dir.resolve()
    config.output_dir.mkdir(parents=True, exist_ok=True)

    model_before = model_before.resolve()
    model_after = model_after.resolve()
    env = check_environment(config)
    if not env.ok or not env.runner:
        result = AdmissibilityResult(
            status="environment_missing",
            admissible=None,
            model_before=str(model_before),
            model_after=str(model_after),
            output_dir=str(config.output_dir),
            environment=env.to_dict(),
            elapsed_sec=round(time.time() - start, 3),
            error="opaal/LTSmin environment is not available",
        )
        return _finalize_result(result)

    work_dir = config.output_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    copied_before = work_dir / _stable_name("model_before", model_before)
    copied_after = work_dir / _stable_name("model_after", model_after)
    shutil.copy2(model_before, copied_before)
    shutil.copy2(model_after, copied_after)
    ts_before = work_dir / f"{copied_before.stem}_lts.xml"
    ts_after = work_dir / f"{copied_after.stem}_lts.xml"
    for old_file in [ts_before, ts_after]:
        if old_file.exists():
            old_file.unlink()

    commands: list[CommandRecord] = []
    equivalence: EquivalenceResult | None = None
    try:
        commands.append(_create_transition_system(copied_before, ts_before, config, env.runner, "create_ts_before"))
        commands.append(_create_transition_system(copied_after, ts_after, config, env.runner, "create_ts_after"))
        equivalence = compare_transition_systems(ts_before, ts_after)
        status = "admissible" if equivalence.equivalent else "inadmissible"
        result = AdmissibilityResult(
            status=status,
            admissible=equivalence.equivalent,
            model_before=str(model_before),
            model_after=str(model_after),
            output_dir=str(config.output_dir),
            environment=env.to_dict(),
            elapsed_sec=round(time.time() - start, 3),
            transition_system_1=str(ts_before) if config.keep_transition_systems else None,
            transition_system_2=str(ts_after) if config.keep_transition_systems else None,
            counterexample=equivalence.counterexample,
            commands=[command.to_dict() for command in commands],
        )
    except (subprocess.TimeoutExpired, OSError, ET.ParseError, AdmissibilityError) as exc:
        result = AdmissibilityResult(
            status="error",
            admissible=None,
            model_before=str(model_before),
            model_after=str(model_after),
            output_dir=str(config.output_dir),
            environment=env.to_dict(),
            elapsed_sec=round(time.time() - start, 3),
            transition_system_1=str(ts_before) if ts_before.exists() else None,
            transition_system_2=str(ts_after) if ts_after.exists() else None,
            commands=[command.to_dict() for command in commands],
            error=str(exc),
        )

    if not config.keep_transition_systems:
        shutil.rmtree(work_dir, ignore_errors=True)
    return _finalize_result(result, equivalence)


def compare_ts_files(ts1: Path, ts2: Path, output_dir: Path) -> AdmissibilityResult:
    """Run only the TARTAR-style untimed equivalence part on existing TS XML."""

    start = time.time()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    ts1 = ts1.resolve()
    ts2 = ts2.resolve()
    env = EnvironmentReport(
        ok=True,
        runner="compare-ts-only",
        tartar_root="",
        opaal_dir="",
        messages=["opaal generation was skipped; existing transition-system XML files were compared"],
    )
    try:
        equivalence = compare_transition_systems(ts1, ts2)
        result = AdmissibilityResult(
            status="admissible" if equivalence.equivalent else "inadmissible",
            admissible=equivalence.equivalent,
            model_before=str(ts1),
            model_after=str(ts2),
            output_dir=str(output_dir),
            environment=env.to_dict(),
            elapsed_sec=round(time.time() - start, 3),
            transition_system_1=str(ts1),
            transition_system_2=str(ts2),
            counterexample=equivalence.counterexample,
        )
        return _finalize_result(result, equivalence)
    except (ET.ParseError, OSError) as exc:
        result = AdmissibilityResult(
            status="error",
            admissible=None,
            model_before=str(ts1),
            model_after=str(ts2),
            output_dir=str(output_dir),
            environment=env.to_dict(),
            elapsed_sec=round(time.time() - start, 3),
            error=str(exc),
        )
        return _finalize_result(result)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TARTAR-style admissibility checker.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    env = subparsers.add_parser("env", help="Check whether opaal/LTSmin can run.")
    env.add_argument("--tartar-root", type=Path, default=DEFAULT_TARTAR_ROOT)
    env.add_argument("--runner", choices=["auto", "native", "wsl"], default="auto")
    env.add_argument("--output-dir", type=Path, default=Path("experiments/admissibility_env"))

    check = subparsers.add_parser("check", help="Check two UPPAAL models.")
    check.add_argument("--model-before", type=Path, required=True)
    check.add_argument("--model-after", type=Path, required=True)
    check.add_argument("--tartar-root", type=Path, default=DEFAULT_TARTAR_ROOT)
    check.add_argument("--output-dir", type=Path, default=Path("experiments/admissibility"))
    check.add_argument("--runner", choices=["auto", "native", "wsl"], default="auto")
    check.add_argument("--timeout", type=int, default=3600)
    check.add_argument("--discard-transition-systems", action="store_true")

    compare = subparsers.add_parser("compare-ts", help="Compare existing opaal transition-system XML files.")
    compare.add_argument("--ts1", type=Path, required=True)
    compare.add_argument("--ts2", type=Path, required=True)
    compare.add_argument("--output-dir", type=Path, default=Path("experiments/admissibility_compare_ts"))
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.command == "env":
        config = AdmissibilityConfig(
            tartar_root=args.tartar_root,
            output_dir=args.output_dir,
            runner=args.runner,
        )
        report = check_environment(config)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        _write_json(args.output_dir / "environment_report.json", report.to_dict())
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0 if report.ok else 3

    if args.command == "compare-ts":
        result = compare_ts_files(args.ts1, args.ts2, args.output_dir)
    else:
        config = AdmissibilityConfig(
            tartar_root=args.tartar_root,
            output_dir=args.output_dir,
            runner=args.runner,
            timeout=args.timeout,
            keep_transition_systems=not args.discard_transition_systems,
        )
        result = check_admissibility(args.model_before, args.model_after, config)

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    if result.status == "admissible":
        return 0
    if result.status == "inadmissible":
        return 1
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
