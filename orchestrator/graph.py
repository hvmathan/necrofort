#!/usr/bin/env python3
"""NecroFort orchestrator: the resurrection state machine.

    PARSE -> SPEC -> TRANSMUTE -> ORACLE_GATE -> PR -> DONE
                                     |   ^
                                     v   |
                                   SELF_HEAL   (max 5 attempts, then BLOCKED)

PARSE        f77_analyzer parses the fixed-form target.
SPEC         Writes the generated Kiro spec (spec.json / spec.md) and picks the
             in-scope units in leaves-first order.
TRANSMUTE    Stages the Rust translations (oracle-harness) in an isolated
             workspace and checks every scheduled unit has a Rust port and a
             differential property. With --demo-bug it plants a realistic F77
             translation fault (a 1-based subscript copied literally).
ORACLE_GATE  gfortran -std=legacy on the extracted units, cargo test (proptest vs
             the gfortran oracle), cargo clippy --all-targets -D warnings,
             wasm-pack build --target web. Stops at the first failing check.
SELF_HEAL    Repairs the Rust code from the shrunk proptest counterexample only,
             then re-enters the gate.
PR           Records the pull-request payload (dry run), opens a draft PR, or
             records the status of an existing PR.

Everything runs locally. The repository itself is never modified: work happens
in a copy under orchestrator/.work/. The run is written to run_log.json for the
web UI. Standard library only.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import f77_analyzer  # noqa: E402

RUN_LOG_SCHEMA = "necrofort.run_log/v1"
MAX_HEAL_ATTEMPTS = 5  # hard cap from .kiro/steering/verification-loop.md

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET = Path("targets/bioumat/SUBROUTINES.FOR")
CRATE = Path("oracle-harness")

# F77 unit -> Rust function in oracle-harness/src/lib.rs. The differential test
# for each is named `<rust>_matches_oracle*` in tests/differential_pbt.rs.
RUST_REGISTRY = {
    "TRANSPOSE": "transpose",
    "DETERMINANT": "determinant",
    "VMATMUL": "vmatmul",
    "TENF": "tenf",
    "UMAT": "umat",
}
NOT_SCHEDULED = {
    "FLOW": "pore-fluid flow boundary condition; not part of the stress kernel (later phase)",
}


class State(str, Enum):
    PARSE = "PARSE"
    SPEC = "SPEC"
    TRANSMUTE = "TRANSMUTE"
    ORACLE_GATE = "ORACLE_GATE"
    SELF_HEAL = "SELF_HEAL"
    PR = "PR"
    DONE = "DONE"
    BLOCKED = "BLOCKED"


TRANSITIONS: dict[State, set[State]] = {
    State.PARSE: {State.SPEC, State.BLOCKED},
    State.SPEC: {State.TRANSMUTE, State.BLOCKED},
    State.TRANSMUTE: {State.ORACLE_GATE, State.BLOCKED},
    State.ORACLE_GATE: {State.PR, State.SELF_HEAL, State.BLOCKED},
    State.SELF_HEAL: {State.ORACLE_GATE, State.BLOCKED},
    State.PR: {State.DONE, State.BLOCKED},
    State.DONE: set(),
    State.BLOCKED: set(),
}


class TransitionError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def tail(text: str, n: int = 30) -> str:
    return "\n".join(text.rstrip().splitlines()[-n:])


# ---------------------------------------------------------------------------
# Command execution (swappable for tests)
# ---------------------------------------------------------------------------


@dataclass
class CommandResult:
    cmd: list[str]
    returncode: int
    output: str
    duration_ms: int

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class CommandRunner:
    def __init__(self, env: dict[str, str] | None = None):
        self.env = {**os.environ, **(env or {})}

    def run(self, cmd: list[str], cwd: Path, timeout: int = 1800,
            stdin: str | None = None) -> CommandResult:
        t0 = time.monotonic()
        try:
            p = subprocess.run(cmd, cwd=cwd, env=self.env, input=stdin, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
            code, out = p.returncode, p.stdout
        except FileNotFoundError as e:
            code, out = 127, f"{cmd[0]}: not found ({e})"
        except subprocess.TimeoutExpired as e:
            code, out = 124, f"timeout after {timeout}s\n{e.output or ''}"
        return CommandResult(cmd, code, out, int((time.monotonic() - t0) * 1000))


# ---------------------------------------------------------------------------
# Parsing cargo test output
# ---------------------------------------------------------------------------

CASES_RE = re.compile(r"^(?:test \S+ \.\.\. )?\.?([a-z0-9_]+): (\d+) cases passed$", re.M)
BIT_RE = re.compile(r"^([a-z0-9_]+): bit-identical (\d+)/(\d+) output entries$", re.M)
CX_RE = re.compile(r"NECRO_COUNTEREXAMPLE (\{.*\})")
FAILED_PROP_RE = re.compile(r"^([a-z0-9_]+) FAILED \(after (\d+) evaluations", re.M)
MINIMAL_RE = re.compile(r"^minimal failing input: (.*)$", re.M)
RESULT_RE = re.compile(r"test result: (\w+)\. (\d+) passed; (\d+) failed")


def routine_for_test(test: str) -> str | None:
    for unit, rust in RUST_REGISTRY.items():
        if test.startswith(rust + "_"):
            return unit
    return None


def parse_cargo_test(output: str) -> dict:
    per_test = {m.group(1): int(m.group(2)) for m in CASES_RE.finditer(output)}
    per_routine: dict[str, int] = {}
    for t, n in per_test.items():
        r = routine_for_test(t)
        if r:
            per_routine[r] = per_routine.get(r, 0) + n
    passed = sum(int(m.group(2)) for m in RESULT_RE.finditer(output))
    failed = sum(int(m.group(3)) for m in RESULT_RE.finditer(output))
    bit = [{"test": m.group(1), "identical": int(m.group(2)), "total": int(m.group(3))}
           for m in BIT_RE.finditer(output)]
    cx = None
    m = CX_RE.search(output)
    if m:
        try:
            cx = json.loads(m.group(1))
        except json.JSONDecodeError:
            cx = {"unparsed": m.group(1)}
        fp = FAILED_PROP_RE.search(output)
        mi = MINIMAL_RE.search(output)
        cx["property"] = fp.group(1) if fp else None
        cx["evaluations"] = int(fp.group(2)) if fp else None
        cx["minimal_input"] = mi.group(1) if mi else None
    return {
        "properties": per_test,
        "cases_per_routine": per_routine,
        "total_cases": sum(per_test.values()),
        "tests_passed": passed,
        "tests_failed": failed,
        "bit_identical": bit,
        "counterexample": cx,
    }


# ---------------------------------------------------------------------------
# Self-heal
# ---------------------------------------------------------------------------


@dataclass
class HealResult:
    applied: bool
    strategy: str
    rationale: str
    file: str | None = None
    line: int | None = None
    before: str | None = None
    after: str | None = None
    evidence: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def find_rust_fn(lines: list[str], name: str) -> tuple[int, int]:
    """0-based [start, end) line range of `pub fn name(` including its body."""
    start = next((i for i, l in enumerate(lines) if re.match(rf"\s*pub fn {name}\s*\(", l)), None)
    if start is None:
        raise KeyError(f"pub fn {name} not found")
    depth, seen = 0, False
    for i in range(start, len(lines)):
        code = lines[i].split("//", 1)[0]
        depth += code.count("{") - code.count("}")
        seen = seen or "{" in code
        if seen and depth == 0:
            return start, i + 1
    raise ValueError(f"unbalanced braces in fn {name}")


class IndexOffsetHealer:
    """Repairs off-by-one subscript faults from a shrunk counterexample.

    The only inputs are the counterexample (routine, mismatching output entry,
    Rust and oracle values, shrunk inputs) and the Rust source being repaired.
    It locates the Rust statement that produces the failing entry via its
    `// F77:` annotation (e.g. `// M(3,1)=V(5)`), finds the input element whose
    value equals the oracle's output, and rewrites the subscript if the Rust line
    demonstrably read a different element. Faults outside this class are left
    for a human or a stronger agent (the healer returns applied=False).
    """

    name = "index-offset"

    def heal(self, cx: dict, lib_rs: Path, rel: str = "oracle-harness/src/lib.rs") -> HealResult:
        routine, entry = cx.get("routine"), cx.get("entry")
        rust_fn = RUST_REGISTRY.get(routine or "")
        if not rust_fn or not entry:
            return HealResult(False, self.name, f"no Rust mapping for routine {routine!r}")
        lines = lib_rs.read_text().splitlines(keepends=True)
        try:
            start, end = find_rust_fn(lines, rust_fn)
        except (KeyError, ValueError) as e:
            return HealResult(False, self.name, str(e))
        ann = re.compile(r"//\s*" + re.escape(entry) + r"\s*=\s*(?P<rhs>.+?)\s*$")
        for idx in range(start, end):
            m = ann.search(lines[idx])
            if not m:
                continue
            code = lines[idx].split("//", 1)[0]
            if "=" not in code:
                continue
            lhs, rhs = code.split("=", 1)
            for var, k_str in re.findall(r"\b([a-z_][a-z0-9_]*)\[(\d+)\]", rhs):
                arr = (cx.get("inputs") or {}).get(var.upper())
                if not isinstance(arr, list):
                    continue
                k = int(k_str)
                oracle, rust = cx.get("oracle"), cx.get("rust")
                read_k = arr[k] if k < len(arr) else None
                evidence = {
                    "input": var.upper(), "rust_read_index0": k, "rust_read_value": read_k,
                    "oracle_value": oracle, "rust_value": rust,
                }
                if read_k is None or read_k == oracle or read_k != rust:
                    continue  # this access does not explain the mismatch
                candidates = [i for i, x in enumerate(arr) if x == oracle]
                f77 = re.search(rf"\b{var.upper()}\((\d+)\)", m.group("rhs"))
                expected = int(f77.group(1)) - 1 if f77 else None
                evidence |= {"candidates_index0": candidates, "f77_subscript": m.group("rhs")}
                if expected is not None and expected in candidates:
                    choice, why = expected, (
                        f"oracle value equals {var.upper()}({expected + 1}), the subscript in the "
                        f"F77 statement {entry}={m.group('rhs')}")
                else:
                    near = [c for c in candidates if abs(c - k) == 1]
                    if len(near) != 1:
                        continue
                    choice, why = near[0], f"oracle value equals the neighbouring element {near[0]}"
                fixed_rhs = re.sub(rf"\b{var}\[{k}\]", f"{var}[{choice}]", rhs, count=1)
                new_line = lhs + "=" + fixed_rhs + lines[idx][len(code):]
                before = lines[idx]
                lines[idx] = new_line
                lib_rs.write_text("".join(lines))
                return HealResult(
                    True, self.name,
                    f"{routine} {entry}: Rust read {var}[{k}] ({var.upper()}({k + 1})) = {read_k!r} "
                    f"but the oracle produced {oracle!r}; {why}. 0-based index is {choice}, "
                    f"so {var}[{k}] -> {var}[{choice}] (1-based subscript copied literally).",
                    rel, idx + 1, before.rstrip("\n"), new_line.rstrip("\n"), evidence)
        return HealResult(False, self.name,
                          f"no annotated statement for {entry} in fn {rust_fn} explains the "
                          f"counterexample as an index offset")


# ---------------------------------------------------------------------------
# Demo bug
# ---------------------------------------------------------------------------

DEMO_BUG = {
    "routine": "TENF",
    "rust_fn": "tenf",
    "find": "m[ix(3, 1)] = v[4]; // M(3,1)=V(5)",
    "replace": "m[ix(3, 1)] = v[5]; // M(3,1)=V(5)",
    "description": (
        "0-based vs 1-based slip: the F77 statement M(3,1)=V(5) was transmuted with the "
        "Fortran subscript copied literally, so Rust reads v[5] (= V(6)) instead of v[4]. "
        "It compiles, passes clippy, and stays in bounds for N=6, so only the differential "
        "test can catch it."
    ),
}


def plant_demo_bug(lib_rs: Path) -> dict:
    src = lib_rs.read_text()
    if DEMO_BUG["find"] not in src:
        raise RuntimeError("demo bug anchor not found in lib.rs")
    line_no = src[: src.index(DEMO_BUG["find"])].count("\n") + 1
    lib_rs.write_text(src.replace(DEMO_BUG["find"], DEMO_BUG["replace"], 1))
    return {
        "routine": DEMO_BUG["routine"],
        "file": "oracle-harness/src/lib.rs",
        "line": line_no,
        "before": DEMO_BUG["find"],
        "after": DEMO_BUG["replace"],
        "description": DEMO_BUG["description"],
    }


# ---------------------------------------------------------------------------
# Run log
# ---------------------------------------------------------------------------


class RunLog:
    def __init__(self, path: Path, mode: str, args: dict):
        self.path = path
        self.data: dict = {
            "schema": RUN_LOG_SCHEMA,
            "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            "mode": mode,
            "args": args,
            "started_at": now(),
            "finished_at": None,
            "outcome": None,
            "graph": {
                "states": [s.value for s in State],
                "edges": [[a.value, b.value] for a, bs in TRANSITIONS.items() for b in sorted(bs)],
            },
            "host": {"platform": platform.platform(), "python": platform.python_version()},
            "toolchain": {},
            "target": {},
            "scope": {},
            "transitions": [],
            "steps": [],
            "planted_bug": None,
            "counterexamples": [],
            "heals": [],
            "gate_runs": [],
            "parity": None,
            "pr": None,
            "blocker": None,
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2) + "\n")

    def transition(self, src: State | None, dst: State, reason: str) -> None:
        self.data["transitions"].append({"seq": len(self.data["transitions"]) + 1,
                                         "from": src.value if src else None,
                                         "to": dst.value, "at": now(), "reason": reason})

    def step(self, state: State, started_at: str, t0: float, status: str, summary: str,
             details: dict | None = None) -> dict:
        rec = {
            "seq": len(self.data["steps"]) + 1,
            "state": state.value,
            "started_at": started_at,
            "finished_at": now(),
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "status": status,
            "summary": summary,
            "details": details or {},
        }
        self.data["steps"].append(rec)
        self.save()
        return rec


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class Orchestrator:
    def __init__(self, repo: Path = REPO_ROOT, out_dir: Path | None = None,
                 work_dir: Path | None = None, demo_bug: bool = False,
                 max_heals: int = MAX_HEAL_ATTEMPTS, pr_mode: str = "dry-run",
                 pr_number: int | None = None, gh_repo: str = "hvmathan/necrofort",
                 base: str = "main", head: str | None = None,
                 runner: CommandRunner | None = None, healer: IndexOffsetHealer | None = None,
                 log_name: str = "run_log.json"):
        if not 1 <= max_heals <= MAX_HEAL_ATTEMPTS:
            raise ValueError(f"max_heals must be 1..{MAX_HEAL_ATTEMPTS}")
        self.repo = repo
        self.out_dir = out_dir or repo / "orchestrator" / "out"
        self.work = work_dir or repo / "orchestrator" / ".work"
        self.ws = self.work / "workspace"
        self.demo_bug = demo_bug
        self.max_heals = max_heals
        self.pr_mode, self.pr_number, self.gh_repo = pr_mode, pr_number, gh_repo
        self.base, self.head = base, head
        self.runner = runner or CommandRunner({"CARGO_TARGET_DIR": str(self.work / "target")})
        self.healer = healer or IndexOffsetHealer()
        self.state: State | None = None
        self.spec: dict = {}
        self.schedule: list[str] = []
        self.heal_attempts = 0
        self.last_gate: dict | None = None
        self.log = RunLog(self.out_dir / log_name, "demo-bug" if demo_bug else "standard", {
            "demo_bug": demo_bug, "max_heals": max_heals, "pr_mode": pr_mode,
            "pr_number": pr_number,
        })

    # -- state machine ------------------------------------------------------
    def go(self, dst: State, reason: str) -> None:
        if self.state is not None and dst not in TRANSITIONS[self.state]:
            raise TransitionError(f"illegal transition {self.state.value} -> {dst.value}")
        self.log.transition(self.state, dst, reason)
        self.state = dst

    def run(self) -> dict:
        self.log.data["toolchain"] = self.toolchain()
        self.go(State.PARSE, "start")
        handlers = {
            State.PARSE: self.do_parse,
            State.SPEC: self.do_spec,
            State.TRANSMUTE: self.do_transmute,
            State.ORACLE_GATE: self.do_gate,
            State.SELF_HEAL: self.do_heal,
            State.PR: self.do_pr,
        }
        while self.state not in (State.DONE, State.BLOCKED):
            nxt, reason = handlers[self.state]()
            self.go(nxt, reason)
        self.log.data["outcome"] = "success" if self.state == State.DONE else "blocked"
        self.log.data["finished_at"] = now()
        self.log.save()
        return self.log.data

    def block(self, state: State, message: str, details: dict | None = None) -> tuple[State, str]:
        self.log.data["blocker"] = {"state": state.value, "message": message,
                                    "details": details or {}}
        return State.BLOCKED, message

    # -- tools --------------------------------------------------------------
    def toolchain(self) -> dict:
        tools = {
            "gfortran": ["gfortran", "--version"],
            "cargo": ["cargo", "--version"],
            "rustc": ["rustc", "--version"],
            "wasm_pack": ["wasm-pack", "--version"],
        }
        out = {}
        for k, cmd in tools.items():
            r = self.runner.run(cmd, self.repo, timeout=60)
            out[k] = r.output.strip().splitlines()[0] if r.ok and r.output.strip() else None
        return out

    # -- PARSE --------------------------------------------------------------
    def do_parse(self) -> tuple[State, str]:
        t0, at = time.monotonic(), now()
        path = self.repo / TARGET
        try:
            self.spec = f77_analyzer.analyze(path, source_label=str(TARGET))
        except OSError as e:
            self.log.step(State.PARSE, at, t0, "failed", str(e))
            return self.block(State.PARSE, f"cannot read {TARGET}: {e}")
        s = self.spec["summary"]
        self.log.data["target"] = self.spec["source"]
        self.log.step(State.PARSE, at, t0, "ok",
                      f"{s['units']} units, {s['gotos']} GO TOs ({s['backward_gotos']} backward), "
                      f"{s['common_blocks']} COMMON blocks, hazards {s['hazards']}",
                      {"units": [{"name": u["name"], "kind": u["kind"],
                                  "lines": [u["line_start"], u["line_end"]]}
                                 for u in self.spec["units"]],
                       "summary": s})
        return State.SPEC, "parsed"

    # -- SPEC ---------------------------------------------------------------
    def do_spec(self) -> tuple[State, str]:
        t0, at = time.monotonic(), now()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "spec.json").write_text(json.dumps(self.spec, indent=2) + "\n")
        (self.out_dir / "spec.md").write_text(f77_analyzer.to_markdown(self.spec))
        errors = {u["name"]: [h["code"] for h in u["hazards"] if h["severity"] == "error"]
                  for u in self.spec["units"]}
        scope = {}
        for name in self.spec["schedule"]:
            if errors.get(name):
                scope[name] = {"status": "out_of_scope",
                               "reason": f"does not compile as written: {', '.join(errors[name])}"}
            elif name in RUST_REGISTRY:
                scope[name] = {"status": "scheduled", "rust": RUST_REGISTRY[name]}
            else:
                scope[name] = {"status": "not_scheduled",
                               "reason": NOT_SCHEDULED.get(name, "no Rust port registered")}
        self.schedule = [n for n, v in scope.items() if v["status"] == "scheduled"]
        self.log.data["scope"] = scope
        self.log.step(State.SPEC, at, t0, "ok",
                      f"spec.json + spec.md written; scheduled {' -> '.join(self.schedule)}",
                      {"spec_json": str((self.out_dir / "spec.json").relative_to(self.repo))
                       if self.out_dir.is_relative_to(self.repo) else str(self.out_dir),
                       "schedule": self.schedule, "scope": scope})
        if not self.schedule:
            return self.block(State.SPEC, "nothing to resurrect")
        return State.TRANSMUTE, "spec ready"

    # -- TRANSMUTE ----------------------------------------------------------
    def do_transmute(self) -> tuple[State, str]:
        t0, at = time.monotonic(), now()
        if self.ws.exists():
            shutil.rmtree(self.ws)
        ignore = shutil.ignore_patterns("target", "pkg", "proptest-regressions")
        shutil.copytree(self.repo / CRATE, self.ws / CRATE, ignore=ignore)
        shutil.copytree(self.repo / TARGET.parent, self.ws / TARGET.parent)
        lib = (self.ws / CRATE / "src" / "lib.rs").read_text()
        tests = (self.ws / CRATE / "tests" / "differential_pbt.rs").read_text()
        units, missing = [], []
        for name in self.schedule:
            rust = RUST_REGISTRY[name]
            has_fn = re.search(rf"^pub fn {rust}\s*\(", lib, re.M) is not None
            has_prop = re.search(rf"fn {rust}_matches_oracle\w*\s*\(", tests) is not None
            units.append({"unit": name, "rust": rust, "port": has_fn, "property": has_prop})
            if not (has_fn and has_prop):
                missing.append(name)
        details = {"workspace": str(self.ws), "units": units}
        if missing:
            self.log.step(State.TRANSMUTE, at, t0, "failed", f"missing ports: {missing}", details)
            return self.block(State.TRANSMUTE, f"no Rust port or property for {', '.join(missing)}")
        if self.demo_bug:
            bug = plant_demo_bug(self.ws / CRATE / "src" / "lib.rs")
            self.log.data["planted_bug"] = bug
            details["planted_bug"] = bug
        self.log.step(State.TRANSMUTE, at, t0, "ok",
                      f"{len(units)} Rust ports staged" + (" (demo bug planted in TENF)"
                                                           if self.demo_bug else ""), details)
        return State.ORACLE_GATE, "translations staged"

    # -- ORACLE_GATE --------------------------------------------------------
    def gate_gfortran(self) -> dict:
        gate_dir = self.ws / "gate"
        gate_dir.mkdir(parents=True, exist_ok=True)
        src = (self.ws / TARGET).read_text("latin-1")
        (gate_dir / "kernels.f").write_text(f77_analyzer.extract_units(src, self.schedule))
        (gate_dir / "ABA_PARAM.INC").write_text(f77_analyzer.ABA_PARAM_INC)
        r = self.runner.run(["gfortran", "-std=legacy", "-ffp-contract=off", "-O2", "-c",
                             "kernels.f", "-o", "kernels.o"], gate_dir)
        return self.check("gfortran", r, {"units": self.schedule})

    def gate_cargo_test(self) -> dict:
        # --no-fail-fast: a failing unit test must not hide the differential suite,
        # which is what produces the counterexample for SELF_HEAL.
        r = self.runner.run(["cargo", "test", "--no-fail-fast", "--", "--nocapture",
                             "--test-threads=1"],
                            self.ws / CRATE)
        parsed = parse_cargo_test(r.output)
        return self.check("cargo_test", r, parsed)

    def gate_clippy(self) -> dict:
        r = self.runner.run(["cargo", "clippy", "--all-targets", "--", "-D", "warnings"],
                            self.ws / CRATE)
        return self.check("clippy", r, {})

    def gate_wasm(self) -> dict:
        r = self.runner.run(["wasm-pack", "build", "--target", "web"], self.ws / CRATE)
        pkg = self.ws / CRATE / "pkg"
        wasm = next(iter(sorted(pkg.glob("*.wasm"))), None) if pkg.exists() else None
        dts = pkg / "oracle_harness.d.ts"
        exports = re.findall(r"^export (?:function|class) (\w+)", dts.read_text(), re.M) \
            if dts.exists() else []
        return self.check("wasm_pack", r, {"wasm_bytes": wasm.stat().st_size if wasm else None,
                                           "exports": [e for e in exports
                                                       if e not in ("initSync",)]})

    @staticmethod
    def check(name: str, r: CommandResult, metrics: dict) -> dict:
        return {"check": name, "cmd": " ".join(r.cmd), "ok": r.ok, "returncode": r.returncode,
                "duration_ms": r.duration_ms, "metrics": metrics, "output_tail": tail(r.output)}

    def do_gate(self) -> tuple[State, str]:
        t0, at = time.monotonic(), now()
        attempt = len(self.log.data["gate_runs"]) + 1
        checks = []
        for fn in (self.gate_gfortran, self.gate_cargo_test, self.gate_clippy, self.gate_wasm):
            c = fn()
            checks.append(c)
            if not c["ok"]:
                break
        run = {"attempt": attempt, "checks": checks, "ok": all(c["ok"] for c in checks)
               and len(checks) == 4}
        self.log.data["gate_runs"].append(run)
        self.last_gate = run
        summary = ", ".join(f"{c['check']} {'ok' if c['ok'] else 'FAILED'}" for c in checks)
        if run["ok"]:
            t = checks[1]["metrics"]
            self.log.data["parity"] = {
                "total_cases": t["total_cases"],
                "properties": t["properties"],
                "cases_per_routine": t["cases_per_routine"],
                "bit_identical": t["bit_identical"],
                "tests_passed": t["tests_passed"],
                "routines": self.schedule,
            }
            self.log.step(State.ORACLE_GATE, at, t0, "ok",
                          f"gate attempt {attempt}: {summary}; {t['total_cases']} proptest cases "
                          f"matched the gfortran oracle", run)
            return State.PR, "all 4 checks passed"
        failed = checks[-1]
        self.log.step(State.ORACLE_GATE, at, t0, "failed", f"gate attempt {attempt}: {summary}",
                      run)
        cx = failed["metrics"].get("counterexample") if failed["check"] == "cargo_test" else None
        if cx and "routine" in cx:
            cx = {"attempt": attempt, **cx}
            self.log.data["counterexamples"].append(cx)
            if self.heal_attempts >= self.max_heals:
                return self.block(State.ORACLE_GATE,
                                  f"retry budget exhausted after {self.heal_attempts} self-heal "
                                  f"attempts; last counterexample in {cx['routine']} {cx['entry']}",
                                  {"counterexample": cx, "output_tail": failed["output_tail"]})
            return State.SELF_HEAL, f"counterexample in {cx['routine']} {cx['entry']}"
        return self.block(State.ORACLE_GATE, f"{failed['check']} failed (no counterexample to heal "
                                             f"from): {failed['cmd']}",
                          {"output_tail": failed["output_tail"]})

    # -- SELF_HEAL ----------------------------------------------------------
    def do_heal(self) -> tuple[State, str]:
        t0, at = time.monotonic(), now()
        self.heal_attempts += 1
        cx = self.log.data["counterexamples"][-1]
        # The healer sees only the counterexample and the source it repairs.
        heal_input = {k: cx.get(k) for k in ("routine", "entry", "rust", "oracle", "inputs")}
        lib = self.ws / CRATE / "src" / "lib.rs"
        res = self.healer.heal(heal_input, lib)
        rec = {"attempt": self.heal_attempts, "max_attempts": self.max_heals,
               "counterexample_attempt": cx["attempt"], **res.as_dict()}
        if res.applied:
            ref = (self.repo / CRATE / "src" / "lib.rs").read_text()
            rec["diff"] = "".join(difflib.unified_diff(
                [res.before + "\n"], [res.after + "\n"],
                f"a/{res.file}:{res.line}", f"b/{res.file}:{res.line}"))
            rec["matches_reference_translation"] = lib.read_text() == ref if self.demo_bug else None
        self.log.data["heals"].append(rec)
        if not res.applied:
            self.log.step(State.SELF_HEAL, at, t0, "failed", res.rationale, rec)
            return self.block(State.SELF_HEAL, f"self-heal could not repair: {res.rationale}", rec)
        self.log.step(State.SELF_HEAL, at, t0, "ok",
                      f"attempt {self.heal_attempts}/{self.max_heals}: {res.rationale}", rec)
        return State.ORACLE_GATE, f"patched {res.file}:{res.line}"

    # -- PR -----------------------------------------------------------------
    def pr_payload(self) -> dict:
        p = self.log.data["parity"] or {}
        heals = self.log.data["heals"]
        lines = [
            "Automated by `orchestrator/graph.py`.",
            "",
            f"- Routines: {', '.join(self.schedule)}",
            f"- proptest cases matched against gfortran: {p.get('total_cases')}",
            f"- Gate attempts: {len(self.log.data['gate_runs'])}, self-heals: {len(heals)}",
        ]
        for h in heals:
            lines.append(f"  - heal {h['attempt']}: {h['rationale']}")
        return {"title": "NecroFort: resurrect " + ", ".join(self.schedule),
                "body": "\n".join(lines), "base": self.base, "head": self.head, "draft": True}

    def do_pr(self) -> tuple[State, str]:
        t0, at = time.monotonic(), now()
        payload = self.pr_payload()
        pr: dict = {"mode": self.pr_mode, "payload": payload}
        if self.pr_mode == "status":
            if not self.pr_number:
                return self.block(State.PR, "--pr-mode status needs --pr-number")
            r = self.runner.run(["gh", "api", f"repos/{self.gh_repo}/pulls/{self.pr_number}"],
                                self.repo, timeout=60)
            if not r.ok:
                self.log.step(State.PR, at, t0, "failed", "gh api failed",
                              {"output_tail": tail(r.output)})
                return self.block(State.PR, f"cannot read PR #{self.pr_number}",
                                  {"output_tail": tail(r.output)})
            pr |= extract_pr(json.loads(r.output))
        elif self.pr_mode == "open":
            if not self.head:
                return self.block(State.PR, "--pr-mode open needs --head <branch> (already pushed)")
            r = self.runner.run(["gh", "api", f"repos/{self.gh_repo}/pulls",
                                 "-f", f"title={payload['title']}", "-f", f"body={payload['body']}",
                                 "-f", f"head={self.head}", "-f", f"base={self.base}",
                                 "-F", "draft=true"], self.repo, timeout=60)
            if not r.ok:
                self.log.step(State.PR, at, t0, "failed", "gh api failed",
                              {"output_tail": tail(r.output)})
                return self.block(State.PR, "could not open PR", {"output_tail": tail(r.output)})
            pr |= extract_pr(json.loads(r.output))
        else:
            pr["state"] = "dry-run"
        self.log.data["pr"] = pr
        self.log.step(State.PR, at, t0, "ok",
                      f"PR {pr.get('state')}" + (f": {pr['html_url']}" if pr.get("html_url") else ""),
                      pr)
        return State.DONE, "done"


def extract_pr(d: dict) -> dict:
    return {
        "number": d.get("number"),
        "html_url": d.get("html_url"),
        "state": "merged" if d.get("merged_at") else d.get("state"),
        "draft": d.get("draft"),
        "title": d.get("title"),
        "head": (d.get("head") or {}).get("ref"),
        "head_sha": (d.get("head") or {}).get("sha"),
        "base": (d.get("base") or {}).get("ref"),
        "updated_at": d.get("updated_at"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="NecroFort resurrection state machine")
    ap.add_argument("--demo-bug", action="store_true",
                    help="plant a 1-based-subscript fault in TENF to demonstrate self-heal")
    ap.add_argument("--max-heals", type=int, default=MAX_HEAL_ATTEMPTS,
                    help=f"self-heal attempts before BLOCKED (1..{MAX_HEAL_ATTEMPTS})")
    ap.add_argument("--pr-mode", choices=["dry-run", "open", "status"], default="dry-run")
    ap.add_argument("--pr-number", type=int)
    ap.add_argument("--repo", default="hvmathan/necrofort", help="GitHub owner/name")
    ap.add_argument("--head", help="branch for --pr-mode open (must already be pushed)")
    ap.add_argument("--base", default="main")
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument("--work-dir", type=Path)
    ap.add_argument("--log-name", default="run_log.json")
    a = ap.parse_args(argv)
    orch = Orchestrator(out_dir=a.out_dir, work_dir=a.work_dir, demo_bug=a.demo_bug,
                        max_heals=a.max_heals, pr_mode=a.pr_mode, pr_number=a.pr_number,
                        gh_repo=a.repo, base=a.base, head=a.head, log_name=a.log_name)
    log = orch.run()
    for s in log["steps"]:
        print(f"[{s['seq']:>2}] {s['state']:<12} {s['status']:<7} {s['duration_ms']:>7} ms  "
              f"{s['summary']}")
    print(f"outcome: {log['outcome']}  ->  {orch.log.path}")
    if log["blocker"]:
        print(f"BLOCKED: {log['blocker']['message']}", file=sys.stderr)
    return 0 if log["outcome"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
