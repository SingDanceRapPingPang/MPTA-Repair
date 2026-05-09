#!/usr/bin/env python3
"""Run original TARTAR repair jobs for the two-fault CSMA/CD dataset."""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "models" / "bound2_dataset" / "csma_cd" / "2csma"
DEFAULT_OUT = ROOT / "experiments" / "original_tartar_bound2_csma"
TARTAR_DIR = ROOT / "TarTar-master" / "tartar"
WRAPPER = ROOT / "tools" / "run_with_uppaal_blacklist_server.sh"
JAR = "../release/tartar.main-3.1.0.jar"
REPAIR_KINDS = ["BOUNDARY", "RESET", "URGENT", "COMPARISON", "REFERENCE"]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        resolved = path.resolve()
        workspace = ROOT.resolve()
        if not str(resolved).lower().startswith(str(workspace).lower()):
            raise RuntimeError(f"Refusing to delete outside workspace: {resolved}")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def wsl_path(path: Path) -> str:
    result = subprocess.run(
        ["wsl", "-e", "wslpath", "-a", str(path)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout.strip()


def read_properties(path: Path) -> list[str]:
    formulas: list[str] = []
    for raw in read_text(path).splitlines():
        line = raw.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        formulas.append(line.rstrip(";"))
    return formulas


def write_model_with_queries(model: Path, properties: Path, dest: Path) -> list[str]:
    formulas = read_properties(properties)
    text = read_text(model)
    text = re.sub(r"<queries>.*?</queries>", "", text, flags=re.S)
    queries = ["  <queries>"]
    for formula in formulas:
        queries.extend(
            [
                "    <query>",
                f"      <formula>{html.escape(formula)}</formula>",
                "      <comment></comment>",
                "    </query>",
            ]
        )
    queries.append("  </queries>")
    if "</nta>" not in text:
        raise ValueError(f"missing </nta> in {model}")
    write_text(dest, text.replace("</nta>", "\n".join(queries) + "\n</nta>"))
    return formulas


def parse_tartar_result(stdout: str, stderr: str, returncode: int) -> dict:
    symbolic_candidates = [
        line
        for line in re.findall(r"^.*Search repair \d+:\s+.*$", stdout, flags=re.M)
        if not line.rstrip().endswith("[]")
    ]
    printed_repairs = re.findall(r"^\s*Repair/", stdout, flags=re.M)
    inadmissible = len(re.findall(r"\bInadmissible:", stdout))
    admissible = len(re.findall(r"\bAdmissible:", stdout))
    no_trace = "No trace file found" in stdout
    qe_failed = "Run QE failed" in stdout or "Z3Exception" in stdout or "Exception" in stderr
    timed_out = returncode == 124
    normal = returncode == 0 and not qe_failed and not no_trace
    return {
        "symbolic_repair_candidates": len(symbolic_candidates),
        "printed_repairs": len(printed_repairs),
        "inadmissible_candidates": inadmissible,
        "admissible_candidates": max(0, admissible),
        "successful_repair": max(0, admissible) > 0 or len(printed_repairs) > 0,
        "normal_completion": normal,
        "no_counterexample": no_trace,
        "qe_failed_or_exception": qe_failed,
        "timed_out": timed_out,
    }


def run_job(
    mod_dir: Path,
    repair_kind: str,
    output_root: Path,
    job_timeout: int,
    z3_timeout: int,
    java_xmx: str,
) -> dict:
    mod_id = mod_dir.name
    work = output_root / repair_kind.lower() / mod_id
    model_with_queries = work / "model_with_queries.xml"
    formulas = write_model_with_queries(mod_dir / "model.xml", mod_dir / "properties.q", model_with_queries)

    cmd = (
        "cd /mnt/d/study/graduation_project/project/MPTA-Repair/TarTar-master/tartar && "
        "export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64 && "
        "export TARTAR_ROOT=/mnt/d/study/graduation_project/project/MPTA-Repair/TarTar-master && "
        "export PATH=$JAVA_HOME/bin:$TARTAR_ROOT/ltsmin-3.0.2/src/pins2lts-mc:$TARTAR_ROOT/opaal/bin:$PATH && "
        "export PYTHONPATH=$TARTAR_ROOT/opaal:$TARTAR_ROOT/pyuppaal:${PYTHONPATH:-} && "
        "export LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu:/usr/lib/x86_64-linux-gnu/jni:/lib:/usr/lib:/usr/local/lib:../lib:${LD_LIBRARY_PATH:-} && "
        f"timeout {job_timeout}s {wsl_path(WRAPPER)} "
        f"java -Xmx{java_xmx} -jar {JAR} "
        f"-run bound2_csma_{repair_kind.lower()}_{mod_id} Job_RepairComputation "
        f"-Folder {wsl_path(work / 'Job_RepairComputation')} "
        f"-Model {wsl_path(model_with_queries)} "
        f"-TimeoutZ3 {z3_timeout} "
        f"-RepairKind {repair_kind}"
    )
    start = time.time()
    proc = subprocess.run(
        ["wsl", "-e", "bash", "-lc", cmd],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=job_timeout + 90,
    )
    elapsed = time.time() - start
    write_text(work / "stdout.txt", proc.stdout)
    write_text(work / "stderr.txt", proc.stderr)

    result = {
        "id": mod_id,
        "repair_kind": repair_kind,
        "model": str(mod_dir / "model.xml"),
        "formulas": formulas,
        "returncode": proc.returncode,
        "elapsed_sec": round(elapsed, 3),
        "stdout": str(work / "stdout.txt"),
        "stderr": str(work / "stderr.txt"),
    }
    result.update(parse_tartar_result(proc.stdout, proc.stderr, proc.returncode))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--job-timeout", type=int, default=180)
    parser.add_argument("--z3-timeout", type=int, default=120)
    parser.add_argument("--java-xmx", default="4g")
    parser.add_argument("--repair-kinds", default=",".join(REPAIR_KINDS))
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    if not args.dataset.exists():
        raise SystemExit(f"dataset not found: {args.dataset}")
    if not (TARTAR_DIR / JAR).resolve().exists():
        raise SystemExit(f"TARTAR jar not found: {(TARTAR_DIR / JAR).resolve()}")
    if not WRAPPER.exists():
        raise SystemExit(f"wrapper not found: {WRAPPER}")

    repair_kinds = [item.strip().upper() for item in args.repair_kinds.split(",") if item.strip()]
    model_dirs = [path for path in sorted(args.dataset.glob("bound_mod_*")) if (path / "model.xml").exists()]
    if args.limit:
        model_dirs = model_dirs[: args.limit]

    ensure_clean_dir(args.output_root)
    results: list[dict] = []
    for repair_kind in repair_kinds:
        for mod_dir in model_dirs:
            print(f"running {repair_kind} {mod_dir.name}", flush=True)
            results.append(
                run_job(
                    mod_dir=mod_dir,
                    repair_kind=repair_kind,
                    output_root=args.output_root,
                    job_timeout=args.job_timeout,
                    z3_timeout=args.z3_timeout,
                    java_xmx=args.java_xmx,
                )
            )

    successful_ids = sorted({r["id"] for r in results if r["successful_repair"] and r["normal_completion"]})
    candidate_ids = sorted({r["id"] for r in results if r["symbolic_repair_candidates"] > 0})
    best_by_model = {}
    for mod_dir in model_dirs:
        mod_results = [row for row in results if row["id"] == mod_dir.name]
        best_by_model[mod_dir.name] = {
            "successful": any(row["successful_repair"] and row["normal_completion"] for row in mod_results),
            "successful_repair_kinds": [
                row["repair_kind"]
                for row in mod_results
                if row["successful_repair"] and row["normal_completion"]
            ],
            "timed_out_repair_kinds": [row["repair_kind"] for row in mod_results if row["timed_out"]],
            "candidate_repair_kinds": [
                row["repair_kind"]
                for row in mod_results
                if row["symbolic_repair_candidates"] > 0
            ],
        }

    summary = {
        "dataset": str(args.dataset),
        "output_root": str(args.output_root),
        "repair_kinds": repair_kinds,
        "job_timeout": args.job_timeout,
        "z3_timeout": args.z3_timeout,
        "total_models": len(model_dirs),
        "total_jobs": len(results),
        "models_with_symbolic_repair_candidates": len(candidate_ids),
        "models_successfully_repaired": len(successful_ids),
        "successful_model_ids": successful_ids,
        "models_timed_out": len({r["id"] for r in results if r["timed_out"]}),
        "jobs_timed_out": len([r for r in results if r["timed_out"]]),
        "jobs_qe_failed_or_exception": len([r for r in results if r["qe_failed_or_exception"]]),
        "by_model": best_by_model,
        "results": results,
    }
    write_text(args.output_root / "summary.json", json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
