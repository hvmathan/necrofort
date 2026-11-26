import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import f77_analyzer as fa  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
BIOUMAT = REPO / "targets" / "bioumat" / "SUBROUTINES.FOR"


# ---------------------------------------------------------------------------
# Fixed-form lexing
# ---------------------------------------------------------------------------


def test_comment_and_blank_lines():
    assert fa.classify_line(1, "C     a comment").kind == "comment"
    assert fa.classify_line(1, "c lower").kind == "comment"
    assert fa.classify_line(1, "* star").kind == "comment"
    assert fa.classify_line(1, "   ! bang").kind == "comment"
    assert fa.classify_line(1, "     \r\n").kind == "blank"


def test_label_continuation_and_inline_comment():
    ln = fa.classify_line(7, "80     CONTINUE ! loop head\r\n")
    assert (ln.kind, ln.label, ln.continuation, ln.text.strip()) == ("code", 80, False, "CONTINUE")
    cont = fa.classify_line(8, "     1 *DFGRD(i,K1)")
    assert cont.continuation and cont.text.strip() == "*DFGRD(i,K1)"
    assert not fa.classify_line(9, "     0 X=1").continuation  # '0' in col 6 is not continuation


def test_columns_73_to_80_are_ignored():
    line = "      X = 1" + " " * 61 + "SEQ00010"
    ln = fa.classify_line(1, line)
    assert ln.text.strip() == "X = 1"
    assert ln.past_col72 == "SEQ00010"
    # A comment running past column 72 is not code past column 72.
    assert fa.classify_line(1, "      X = 1 ! " + "y" * 80).past_col72 == ""


def test_continuation_lines_join_into_one_statement():
    src = ["      W6=((A+B)", "C     interleaved comment", "     1 *C)"]
    stmts = fa.logical_statements([fa.classify_line(i + 1, l) for i, l in enumerate(src)])
    assert len(stmts) == 1
    assert stmts[0].norm == "W6=((A+B)*C)"
    assert (stmts[0].line_start, stmts[0].line_end) == (1, 3)


# ---------------------------------------------------------------------------
# Synthetic program
# ---------------------------------------------------------------------------

SYNTH = """\
      SUBROUTINE KERNEL(X, N, Y)
      DIMENSION X(N), Y(N)
      COMMON /STATE/ ACC, ITER
      PARAMETER (HALF=0.5D0)
      DO 10 I = 1, N
       Y(I) = X(I)*HALF + ACC
   10 CONTINUE
      ITER = ITER + 1
   20 IF (ITER.LT.3) GO TO 30
      GO TO (20, 30), K
   30 IF (N.GT.0) CALL HELPER(Y, N)
      RETURN
      END
      SUBROUTINE HELPER(Y, N)
      IMPLICIT NONE
      INTEGER N
      DOUBLE PRECISION Y(N)
      Y(1) = 0.0D0
      END
"""


@pytest.fixture
def synth(tmp_path):
    p = tmp_path / "synth.f"
    p.write_text(SYNTH)
    return fa.analyze(p)


def unit(spec, name):
    return next(u for u in spec["units"] if u["name"] == name)


def test_units_signatures_and_schedule(synth):
    assert [u["name"] for u in synth["units"]] == ["KERNEL", "HELPER"]
    k = unit(synth, "KERNEL")
    assert k["signature"] == "SUBROUTINE KERNEL(X, N, Y)"
    assert [a["name"] for a in k["args"]] == ["X", "N", "Y"]
    assert synth["call_graph"] == {"KERNEL": ["HELPER"], "HELPER": []}
    assert synth["schedule"] == ["HELPER", "KERNEL"]  # leaves first


def test_implicit_typing_and_intents(synth):
    k = unit(synth, "KERNEL")
    args = {a["name"]: a for a in k["args"]}
    assert args["X"]["type"] == "REAL" and args["X"]["typing"] == "implicit"
    assert args["N"]["type"] == "INTEGER"
    assert args["X"]["intent"] == "in"
    assert args["Y"]["intent"] == "out"
    assert args["Y"]["rust_type"].startswith("&mut [f32]")
    syms = {s["name"]: s for s in k["symbols"]}
    assert syms["I"]["type"] == "INTEGER" and syms["ACC"]["type"] == "REAL"
    assert syms["HALF"]["role"] == "parameter" and syms["HALF"]["value"] == "0.5D0"
    h = unit(synth, "HELPER")
    assert h["implicit_rules"] == ["A-Z: NONE"]
    assert {a["name"]: a["type"] for a in h["args"]} == {"Y": "REAL*8", "N": "INTEGER"}


def test_common_blocks_labels_and_gotos(synth):
    k = unit(synth, "KERNEL")
    assert k["common_blocks"] == [{"name": "STATE", "line": 3, "members": ["ACC", "ITER"]}]
    syms = {s["name"]: s for s in k["symbols"]}
    assert syms["ITER"]["role"] == "common:/STATE/"
    assert k["labels"] == {"10": 7, "20": 9, "30": 11}
    gotos = [(g["label"], g["kind"], g["direction"]) for g in k["gotos"]]
    assert gotos == [(30, "unconditional", "forward"), (20, "computed", "backward"),
                     (30, "computed", "forward")]
    assert k["do_loops"][0]["var"] == "I" and k["do_loops"][0]["label"] == 10
    assert any("COMMON /STATE/" in c for c in k["acceptance"])


# ---------------------------------------------------------------------------
# Real target: BioUMAT
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def bio():
    return fa.analyze(BIOUMAT, source_label="targets/bioumat/SUBROUTINES.FOR")


def test_bioumat_units_and_ranges(bio):
    got = [(u["name"], u["line_start"], u["line_end"]) for u in bio["units"]]
    assert got == [("SDVINI", 9, 99), ("FLOW", 104, 116), ("UMAT", 122, 392),
                   ("TRANSPOSE", 400, 409), ("DETERMINANT", 413, 419),
                   ("VMATMUL", 423, 435), ("TENF", 439, 461)]
    assert bio["source"]["line_endings"] == "CRLF"
    assert any(h["code"] == "STRAY_END" and h["line"] == 463 for h in bio["file_hazards"])


def test_bioumat_umat_gotos_and_state_hazard(bio):
    u = unit(bio, "UMAT")
    assert [(g["label"], g["line"], g["target_line"], g["direction"]) for g in u["gotos"]] == [
        (80, 368, 247, "backward"), (90, 380, 254, "backward")]
    reuse = [h for h in u["hazards"] if h["code"] == "DO_VAR_REUSED_IN_GOTO_LOOP"]
    assert [(h["line"], "DO variable I" in h["message"]) for h in reuse] == [(277, True)]
    assert any(h["code"] == "INTRINSIC_SHADOWED" and "INDEX" in h["message"] for h in u["hazards"])


def test_bioumat_aba_param_implicit_real8(bio):
    u = unit(bio, "UMAT")
    assert u["includes"] == ["ABA_PARAM.INC"]
    assert u["implicit_rules"] == ["A-H: REAL*8", "I-N: INTEGER", "O-Z: REAL*8"]
    syms = {s["name"]: s for s in u["symbols"]}
    assert syms["GM"]["type"] == "REAL*8" and syms["GM"]["typing"] == "implicit"
    args = {a["name"]: a for a in u["args"]}
    assert args["STRESS"]["intent"] == "out"
    assert args["STATEV"]["intent"] == "inout"
    assert args["DFGRD1"]["intent"] == "inout"  # perturbed in place, then restored
    assert args["CMNAME"]["type"] == "CHARACTER*80"
    # No include in the leaf kernels: default F77 implicit typing.
    assert unit(bio, "TRANSPOSE")["implicit_rules"] == ["A-H: REAL", "I-N: INTEGER", "O-Z: REAL"]


def test_bioumat_sdvini_compile_errors_detected(bio):
    codes = {(h["code"], h["line"]) for h in unit(bio, "SDVINI")["hazards"]}
    assert ("INVALID_CALL_NAME", 40) in codes
    assert ("LOGICAL_OP_ON_INTEGERS", 56) in codes
    assert ("SINGLE_PRECISION_LITERAL", 38) in codes
    assert bio["summary"]["units_with_errors"] == ["SDVINI"]


def test_bioumat_schedule_is_leaves_first(bio):
    order = bio["schedule"]
    for callee in bio["call_graph"]["UMAT"]:
        assert order.index(callee) < order.index("UMAT")
    assert bio["call_graph"]["UMAT"] == ["DETERMINANT", "TENF", "TRANSPOSE", "VMATMUL"]


def test_vmatmul_intents(bio):
    args = {a["name"]: a["intent"] for a in unit(bio, "VMATMUL")["args"]}
    assert args == {"A": "in", "B": "in", "N": "in", "C": "out"}


def test_extract_units_is_verbatim():
    text = BIOUMAT.read_text("latin-1")
    out = fa.extract_units(text, ["VMATMUL"])
    src_lines = text.splitlines()
    assert out.splitlines() == src_lines[422:435]
    with pytest.raises(KeyError):
        fa.extract_units(text, ["NOPE"])


def test_markdown_render(bio):
    md = fa.to_markdown(bio)
    assert "## SUBROUTINE `UMAT` (lines 122-392)" in md
    assert "| GO TO | From line | Target line | Direction |" in md
    assert "Acceptance criteria:" in md


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not installed")
def test_extracted_units_compile_with_gfortran(tmp_path):
    text = BIOUMAT.read_text("latin-1")
    names = ["TRANSPOSE", "DETERMINANT", "VMATMUL", "TENF", "UMAT"]
    (tmp_path / "k.f").write_text(fa.extract_units(text, names))
    (tmp_path / "ABA_PARAM.INC").write_text(fa.ABA_PARAM_INC)
    r = subprocess.run(["gfortran", "-std=legacy", "-c", "k.f"], cwd=tmp_path,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
