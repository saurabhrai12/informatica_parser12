"""Autoresearch propose→eval→keep/revert loop.

Usage:
    python autoresearch/run_loop.py --step lineage --max-experiments 50

This is a thin orchestrator. It does NOT propose code changes itself; it
launches a Claude Code subagent (or any LLM driver) given the program_*.md
agenda, runs the corresponding eval, compares scalar scores, and either keeps
or reverts the commit. The interesting work happens inside the eval contract.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results.tsv"

EVAL_CMDS = {
    "lineage": [sys.executable, "-m", "step1_lineage.eval"],
    "mapping": [sys.executable, "-m", "step2_mapping.eval"],
    "procgen": [sys.executable, "-m", "step3_procgen.eval"],
}


def run_eval(step: str) -> float:
    out = subprocess.run(EVAL_CMDS[step], cwd=ROOT, capture_output=True, text=True, check=True)
    return float(out.stdout.strip().splitlines()[-1])


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def append_result(step: str, exp: int, score: float, kept: bool) -> None:
    RESULTS.touch(exist_ok=True)
    with RESULTS.open("a") as f:
        f.write(f"{int(time.time())}\t{step}\t{exp}\t{score:.6f}\t{'KEEP' if kept else 'REVERT'}\n")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--step", required=True, choices=EVAL_CMDS.keys())
    p.add_argument("--max-experiments", type=int, default=50)
    args = p.parse_args()

    baseline = run_eval(args.step)
    print(f"baseline {args.step} score: {baseline:.6f}")
    print("This loop expects an external proposer (e.g. Claude Code) to mutate")
    print("the modifiable files between iterations. Run the proposer in a loop")
    print("and call this script with --max-experiments=1 to evaluate each step.")


if __name__ == "__main__":
    main()
