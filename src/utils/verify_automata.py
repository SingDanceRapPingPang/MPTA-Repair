"""Utilities for verifying UPPAAL models with verifyta."""

from __future__ import annotations

import subprocess
import tempfile
import time
import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_VERIFYTA = Path(r"D:\tool\programming\uppaal\UPPAAL-5.0.0\bin\verifyta.exe")


@dataclass
class VerificationResult:
    formula: str
    status: str
    duration_sec: float
    exit_code: int | None
    output: str

    @property
    def satisfied(self) -> bool:
        return self.status == "satisfied"


def run_verifyta_command(args: list[str], timeout: int) -> tuple[str, int | None, bool]:
    """Run verifyta and reliably clean up the process tree on timeout."""
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        output, _ = proc.communicate(timeout=timeout)
        return output, proc.returncode, False
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            proc.kill()
        output, _ = proc.communicate()
        return output or "", None, True


def verify_property(
    model_path: str | Path,
    formula: str,
    verifyta_path: str | Path = DEFAULT_VERIFYTA,
    timeout: int = 90,
    options: list[str] | None = None,
) -> VerificationResult:
    """Verify one UPPAAL query formula against a model."""
    model_path = Path(model_path)
    verifyta_path = Path(verifyta_path)
    options = options or ["-q", "-s"]

    with tempfile.TemporaryDirectory(prefix="uppaal_query_") as tmp:
        query_path = Path(tmp) / "property.q"
        query_path.write_text(formula.strip() + "\n", encoding="utf-8")

        start = time.time()
        output, returncode, timed_out = run_verifyta_command(
            [str(verifyta_path), *options, str(model_path), str(query_path)],
            timeout,
        )
        if timed_out:
            return VerificationResult(formula, "timeout", float(timeout), None, output)
        lower = output.lower()
        if "formula is satisfied" in lower:
            status = "satisfied"
        elif "formula is not satisfied" in lower:
            status = "not_satisfied"
        else:
            status = "error"
        return VerificationResult(formula, status, round(time.time() - start, 3), returncode, output)


def verify_query_file(
    model_path: str | Path,
    query_path: str | Path,
    verifyta_path: str | Path = DEFAULT_VERIFYTA,
    timeout: int = 90,
) -> VerificationResult:
    """Verify all queries in an existing .q file as one verifyta invocation."""
    model_path = Path(model_path)
    query_path = Path(query_path)
    verifyta_path = Path(verifyta_path)
    start = time.time()
    output, returncode, timed_out = run_verifyta_command(
        [str(verifyta_path), "-q", "-s", str(model_path), str(query_path)],
        timeout,
    )
    if timed_out:
        return VerificationResult(str(query_path), "timeout", float(timeout), None, output)
    lower = output.lower()
    if "formula is not satisfied" in lower:
        status = "not_satisfied"
    elif "error]" in lower or returncode not in (0,):
        status = "error"
    else:
        status = "satisfied"
    return VerificationResult(str(query_path), status, round(time.time() - start, 3), returncode, output)
