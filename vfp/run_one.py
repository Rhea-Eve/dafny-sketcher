#!/usr/bin/env python3
# Run ONE VFP spec with a chosen solver and write to programs/<name>.dfy
# Usage:
#   ./solve_one_spec.py --solver mcts   specs/idea-6.dfy
#   ./solve_one_spec.py --solver fine   specs/idea-9.dfy
#   ./solve_one_spec.py --solver driver specs/idea-2.dfy
#   ./solve_one_spec.py --solver mcts --overwrite specs/idea-6.dfy

from pathlib import Path
import argparse, sys
import sketcher
import mcts, fine, driver

def pick_solver(name):
    if name == "mcts":   return lambda s: mcts.main(s)
    if name == "fine":   return lambda s: fine.main(s)
    if name == "driver": return lambda s: driver.drive_program(s, 10)
    raise SystemExit(f"Unknown solver: {name}")

def main():
    ap = argparse.ArgumentParser(description="Run ONE Dafny VFP spec and save result to programs/.")
    ap.add_argument("--solver", choices=["mcts","fine","driver"], required=True)
    ap.add_argument("--overwrite", action="store_true", help="Write even if programs/<name>.dfy exists")
    ap.add_argument("spec", help="Path to specs/<file>.dfy")
    args = ap.parse_args()

    spec_path = Path(args.spec)
    if not spec_path.exists():
        raise SystemExit(f"No such file: {spec_path}")
    out = Path("programs") / spec_path.name

    if out.exists() and not args.overwrite:
        print(f"[SKIP] already solved: {out}")
        return 0

    solver = pick_solver(args.solver)
    print(f"=== Solving {spec_path} with {args.solver} ===")
    program = solver(spec_path.read_text())
    if program is None:
        print(f"[FAILED] solver returned None"); return 2

    if sketcher.sketch_next_todo(program) is not None:
        print(f"[GAVE UP] still has TODOs; not writing output")
        print(program)
        return 3

    out.parent.mkdir(exist_ok=True)
    out.write_text(program)
    print(f"[SOLVED] {spec_path} -> {out}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
