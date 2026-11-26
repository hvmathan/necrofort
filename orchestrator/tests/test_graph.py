import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import graph  # noqa: E402
from graph import (CommandResult, HealResult, IndexOffsetHealer, Orchestrator, State,  # noqa: E402
                   TransitionError, parse_cargo_test)

PASS_OUTPUT = """\
running 3 tests
test tenf_matches_oracle ... tenf_matches_oracle: 1024 cases passed
ok
test umat_matches_oracle ... umat_matches_oracle: 1024 cases passed
umat_matches_oracle: bit-identical 40/40 output entries
ok
test vmatmul_matches_oracle_general ... vmatmul_matches_oracle_general: 1024 cases passed
ok
test result: ok. 3 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.1s
"""

CX = {"routine": "TENF", "entry": "M(3,1)", "rust": -5.0, "oracle": 0.0, "tol": 0.0,
      "inputs": {"V": [0.0, 0.0, 0.0, 0.0, 0.0, -5.0]}}
FAIL_OUTPUT = f"""\
test tenf_matches_oracle ... thread 'tenf_matches_oracle' panicked at tests/differential_pbt.rs:1:1:
tenf_matches_oracle FAILED (after 1041 evaluations incl. shrinking)
NECRO_COUNTEREXAMPLE {json.dumps(CX)}
minimal failing input: [0.0, 0.0, 0.0, 0.0, 0.0, -5.0]
test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.1s
"""


class FakeRunner:
    """Scripted command results keyed by the first two words of the command."""

    def __init__(self, script: dict[str, list[tuple[int, str]]]):
        self.script = script
        self.calls: list[list[str]] = []

    def run(self, cmd, cwd, timeout=1800, stdin=None):
        self.calls.append(cmd)
        key = " ".join(cmd[:2])
        seq = self.script.get(key) or self.script.get(cmd[0]) or [(0, f"{cmd[0]} 1.0")]
        code, out = seq.pop(0) if len(seq) > 1 else seq[0]
        return CommandResult(cmd, code, out, 1)


def make(tmp_path, script, **kw) -> Orchestrator:
    return Orchestrator(out_dir=tmp_path / "out", work_dir=tmp_path / "work",
                        runner=FakeRunner(script), **kw)


# ---------------------------------------------------------------------------
# cargo test parsing
# ---------------------------------------------------------------------------


def test_parse_cargo_test_pass():
    p = parse_cargo_test(PASS_OUTPUT)
    assert p["total_cases"] == 3072
    assert p["cases_per_routine"] == {"TENF": 1024, "UMAT": 1024, "VMATMUL": 1024}
    assert p["bit_identical"] == [{"test": "umat_matches_oracle", "identical": 40, "total": 40}]
    assert p["counterexample"] is None and p["tests_passed"] == 3


def test_parse_cargo_test_counterexample():
    cx = parse_cargo_test(FAIL_OUTPUT)["counterexample"]
    assert cx["routine"] == "TENF" and cx["entry"] == "M(3,1)"
    assert cx["property"] == "tenf_matches_oracle" and cx["evaluations"] == 1041
    assert cx["minimal_input"].startswith("[0.0")


# ---------------------------------------------------------------------------
# Healer
# ---------------------------------------------------------------------------

LIB = """\
pub fn tenf(v: &[f64]) -> Result<Mat3, VoigtError> {
    let mut m = [0.0; 9];
    m[ix(1, 1)] = v[0]; // M(1,1)=V(1)
    if n == NTENS_SOLID {
        m[ix(3, 1)] = v[5]; // M(3,1)=V(5)
    }
    Ok(m)
}
"""


def test_healer_fixes_literal_one_based_subscript(tmp_path):
    lib = tmp_path / "lib.rs"
    lib.write_text(LIB)
    res = IndexOffsetHealer().heal(CX, lib)
    assert res.applied, res.rationale
    assert res.line == 5
    assert "m[ix(3, 1)] = v[4]; // M(3,1)=V(5)" in lib.read_text()
    assert res.evidence["candidates_index0"] == [0, 1, 2, 3, 4]


def test_healer_uses_value_when_unambiguous(tmp_path):
    lib = tmp_path / "lib.rs"
    lib.write_text(LIB.replace("// M(3,1)=V(5)", "// M(3,1)=?"))
    cx = CX | {"rust": 2.0, "oracle": 7.0, "inputs": {"V": [0.0, 0.0, 0.0, 0.0, 7.0, 2.0]}}
    res = IndexOffsetHealer().heal(cx, lib)
    assert res.applied and "v[4]" in res.after


def test_healer_declines_non_index_faults(tmp_path):
    lib = tmp_path / "lib.rs"
    lib.write_text(LIB.replace("v[5]", "v[4]"))
    # Rust read the right element; the mismatch is not explained by an index offset.
    cx = CX | {"rust": 1.5, "oracle": 1.0, "inputs": {"V": [0.0, 0.0, 0.0, 0.0, 1.0, 9.0]}}
    res = IndexOffsetHealer().heal(cx, lib)
    assert not res.applied
    assert lib.read_text() == LIB.replace("v[5]", "v[4]")


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


def test_illegal_transition_rejected(tmp_path):
    o = make(tmp_path, {})
    o.go(State.PARSE, "start")
    with pytest.raises(TransitionError):
        o.go(State.PR, "skip the gate")


def test_max_heals_capped_at_five(tmp_path):
    with pytest.raises(ValueError):
        make(tmp_path, {}, max_heals=6)


def test_demo_bug_is_caught_healed_and_logged(tmp_path):
    o = make(tmp_path, {"cargo test": [(101, FAIL_OUTPUT), (0, PASS_OUTPUT)]}, demo_bug=True)
    log = o.run()
    assert log["outcome"] == "success"
    states = [s["state"] for s in log["steps"]]
    assert states == ["PARSE", "SPEC", "TRANSMUTE", "ORACLE_GATE", "SELF_HEAL", "ORACLE_GATE", "PR"]
    assert [t["to"] for t in log["transitions"]][-1] == "DONE"
    assert log["planted_bug"]["routine"] == "TENF"
    assert log["counterexamples"][0]["entry"] == "M(3,1)"
    heal = log["heals"][0]
    assert heal["applied"] and heal["matches_reference_translation"] is True
    assert log["parity"]["total_cases"] == 3072
    assert log["scope"]["SDVINI"]["status"] == "out_of_scope"
    assert log["scope"]["UMAT"]["status"] == "scheduled"
    # The run log on disk matches what run() returned.
    assert json.loads((tmp_path / "out" / "run_log.json").read_text()) == log
    assert (tmp_path / "out" / "spec.json").exists() and (tmp_path / "out" / "spec.md").exists()
    # The repository copy of lib.rs was never touched.
    assert "v[5]; // M(3,1)=V(5)" not in (graph.REPO_ROOT / "oracle-harness/src/lib.rs").read_text()


def test_blocked_after_five_failed_heals(tmp_path):
    class AlwaysApplies:
        def heal(self, cx, lib_rs, rel="x"):
            return HealResult(True, "stub", "pretend fix", rel, 1, "a", "b")

    o = Orchestrator(out_dir=tmp_path / "out", work_dir=tmp_path / "work",
                     runner=FakeRunner({"cargo test": [(101, FAIL_OUTPUT)]}),
                     healer=AlwaysApplies())
    log = o.run()
    assert log["outcome"] == "blocked"
    assert len(log["heals"]) == 5
    assert len(log["gate_runs"]) == 6
    assert "retry budget exhausted" in log["blocker"]["message"]


def test_non_test_failure_blocks_without_healing(tmp_path):
    o = make(tmp_path, {"cargo test": [(0, PASS_OUTPUT)], "cargo clippy": [(101, "error: lint")]})
    log = o.run()
    assert log["outcome"] == "blocked"
    assert log["heals"] == []
    assert "clippy failed" in log["blocker"]["message"]


def test_pr_status_mode_records_github_state(tmp_path):
    pr = {"number": 2, "html_url": "https://github.com/o/r/pull/2", "state": "open",
          "draft": True, "title": "t", "head": {"ref": "feat", "sha": "abc"},
          "base": {"ref": "main"}, "merged_at": None, "updated_at": "2026-11-26T00:00:00Z"}
    o = make(tmp_path, {"cargo test": [(0, PASS_OUTPUT)], "gh api": [(0, json.dumps(pr))]},
             pr_mode="status", pr_number=2)
    log = o.run()
    assert log["outcome"] == "success"
    assert log["pr"]["state"] == "open" and log["pr"]["draft"] is True
    assert log["pr"]["html_url"].endswith("/pull/2")
