#!/usr/bin/env python3
"""Fixed-form Fortran 77 analyzer for NecroFort.

Parses a fixed-form source file (labels in columns 1-5, continuation marker in
column 6, statement text in columns 7-72, columns 73-80 ignored) into program
units with their signatures, symbol tables (explicit and implicit I-N typing),
COMMON blocks, CALL graph, statement labels and GO TO jumps, plus a list of
translation hazards. The result is emitted as a structured Kiro spec in JSON and
Markdown, and drives `graph.py`.

Standard library only. Usage:

    python3 orchestrator/f77_analyzer.py targets/bioumat/SUBROUTINES.FOR \\
        --json orchestrator/out/spec.json --md orchestrator/out/spec.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCHEMA = "necrofort.kiro_spec/v1"

# Minimal stand-in for Abaqus' ABA_PARAM.INC (double-precision build).
# Keep in sync with ABA_PARAM_INC in oracle-harness/build.rs.
ABA_PARAM_INC = "      IMPLICIT REAL*8(A-H,O-Z)\n      PARAMETER (NPRECD=2)\n"
KNOWN_INCLUDES = {"ABA_PARAM.INC": ABA_PARAM_INC}

F77_INTRINSICS = {
    "ABS", "ACOS", "AINT", "ANINT", "ASIN", "ATAN", "ATAN2", "CHAR", "CMPLX",
    "CONJG", "COS", "COSH", "DABS", "DBLE", "DCOS", "DEXP", "DIM", "DLOG",
    "DPROD", "DSIN", "DSQRT", "EXP", "FLOAT", "ICHAR", "IDINT", "IFIX", "INDEX",
    "INT", "LEN", "LGE", "LGT", "LLE", "LLT", "LOG", "LOG10", "MAX", "MIN",
    "MOD", "NINT", "REAL", "SIGN", "SIN", "SINH", "SNGL", "SQRT", "TAN", "TANH",
}
F90_INTRINSICS = {
    "DOT_PRODUCT", "MATMUL", "PRODUCT", "RANDOM_NUMBER", "RESHAPE", "SHAPE",
    "SIZE", "SUM", "TRANSPOSE",
}
KEYWORDS = {
    "CALL", "CHARACTER", "COMMON", "CONTINUE", "DATA", "DIMENSION", "DO",
    "DOUBLE", "ELSE", "ELSEIF", "END", "ENDDO", "ENDIF", "EQUIVALENCE",
    "EXTERNAL", "FORMAT", "FUNCTION", "GO", "GOTO", "IF", "IMPLICIT", "INCLUDE",
    "INTEGER", "INTRINSIC", "LOGICAL", "NONE", "PARAMETER", "PRECISION",
    "PRINT", "PROGRAM", "READ", "REAL", "RETURN", "SAVE", "STOP", "SUBROUTINE",
    "THEN", "TO", "WHILE", "WRITE",
}
RUST_TYPES = {
    "REAL*8": "f64",
    "REAL": "f32",
    "INTEGER": "i32",
    "LOGICAL": "bool",
    "COMPLEX": "num_complex::Complex32",
}

TYPE_RE = re.compile(
    r"^(DOUBLE\s*PRECISION|REAL\s*\*\s*\d+|REAL|INTEGER\s*\*\s*\d+|INTEGER|"
    r"LOGICAL(?:\s*\*\s*\d+)?|COMPLEX(?:\s*\*\s*\d+)?|CHARACTER(?:\s*\*\s*(?:\d+|\(\s*\*\s*\)))?)"
)
UNIT_RE = re.compile(
    r"^(?:(?P<rtype>DOUBLE\s*PRECISION|REAL(?:\s*\*\s*\d+)?|INTEGER(?:\s*\*\s*\d+)?|LOGICAL)\s*)?"
    r"(?P<kind>SUBROUTINE|FUNCTION|PROGRAM)\s+(?P<name>[A-Z][A-Z0-9_]*)\s*(?:\((?P<args>[^)]*)\))?\s*$"
)
END_RE = re.compile(r"^END(?:\s*(?:SUBROUTINE|FUNCTION|PROGRAM)(?:\s+[A-Z][A-Z0-9_]*)?)?$")
DOTTED_OP_RE = re.compile(r"\.(?:EQ|NE|LT|LE|GT|GE|AND|OR|NOT|EQV|NEQV|TRUE|FALSE)\.")
NUMBER_RE = re.compile(
    r"(?<![A-Z0-9_.])(\d+\.\d*|\.\d+|\d+(?=[EDQ][+-]?\d))([EDQ][+-]?\d+)?(?![A-Z0-9_])|(?<![A-Z0-9_.])\d+(?![A-Z0-9_.])"
)
NAME_RE = re.compile(r"\b[A-Z][A-Z0-9_]*\b")


# ---------------------------------------------------------------------------
# Fixed-form lexing
# ---------------------------------------------------------------------------


@dataclass
class SourceLine:
    lineno: int
    kind: str  # "code" | "comment" | "blank"
    label: int | None = None
    continuation: bool = False
    text: str = ""  # columns 7-72 with any inline '!' comment removed
    past_col72: str = ""  # code (not comment) found in columns 73+


@dataclass
class Statement:
    line_start: int
    line_end: int
    label: int | None
    text: str  # joined statement text, original case
    norm: str  # upper-case outside string literals, blanks collapsed


def _find_inline_comment(s: str) -> int:
    """Index of a '!' that starts an inline comment (outside quotes), or -1."""
    in_str = False
    for i, ch in enumerate(s):
        if ch == "'":
            in_str = not in_str
        elif ch == "!" and not in_str:
            return i
    return -1


def classify_line(lineno: int, raw: str) -> SourceLine:
    line = raw.rstrip("\r\n").expandtabs(8)
    if not line.strip():
        return SourceLine(lineno, "blank")
    if line[0] in "Cc*!" or line.lstrip().startswith("!"):
        return SourceLine(lineno, "comment")
    label_field = line[:5]
    continuation = len(line) > 5 and line[5] not in " 0"
    body = line[6:]
    bang = _find_inline_comment(body)
    code = body if bang < 0 else body[:bang]
    stmt, past = code[:66], code[66:]
    if not stmt.strip() and not continuation:
        return SourceLine(lineno, "comment")
    label = int(label_field) if label_field.strip().isdigit() else None
    return SourceLine(lineno, "code", label, continuation, stmt, past.strip())


def normalize(text: str) -> str:
    """Upper-cases outside string literals and collapses runs of blanks."""
    out, in_str = [], False
    for ch in text:
        if ch == "'":
            in_str = not in_str
            out.append(ch)
        else:
            out.append(ch if in_str else ch.upper())
    return re.sub(r"\s+", " ", "".join(out)).strip()


def logical_statements(lines: list[SourceLine]) -> list[Statement]:
    stmts: list[Statement] = []
    for ln in lines:
        if ln.kind != "code":
            continue
        if ln.continuation and stmts:
            prev = stmts[-1]
            prev.text = prev.text.rstrip() + ln.text.strip()
            prev.line_end = ln.lineno
        else:
            stmts.append(Statement(ln.lineno, ln.lineno, ln.label, ln.text.strip(), ""))
    for s in stmts:
        s.norm = normalize(s.text)
    return stmts


# ---------------------------------------------------------------------------
# Expression helpers
# ---------------------------------------------------------------------------


def split_top_level(s: str, sep: str = ",") -> list[str]:
    parts, depth, cur, in_str = [], 0, [], False
    for ch in s:
        if ch == "'":
            in_str = not in_str
        if not in_str:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == sep and depth == 0:
                parts.append("".join(cur).strip())
                cur = []
                continue
        cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur).strip())
    return parts


def match_paren(s: str, start: int) -> int:
    """Index of the ')' matching the '(' at `start`, or -1."""
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "(":
            depth += 1
        elif s[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def strip_literals(expr: str) -> str:
    expr = re.sub(r"'[^']*'", " ", expr)
    expr = DOTTED_OP_RE.sub(" ", expr)
    return NUMBER_RE.sub(" ", expr)


def names_in(expr: str) -> list[str]:
    return [n for n in NAME_RE.findall(strip_literals(expr)) if n not in KEYWORDS]


def real_literals(expr: str) -> list[tuple[str, str]]:
    """(literal, precision) for every real literal in `expr`."""
    expr = DOTTED_OP_RE.sub(" ", re.sub(r"'[^']*'", " ", expr))
    found = []
    for m in NUMBER_RE.finditer(expr):
        if m.group(1) is None:
            continue  # plain integer
        exp = m.group(2) or ""
        found.append((m.group(0), "REAL*8" if exp.startswith("D") else "REAL"))
    return found


def f32_exact(lit: str) -> bool:
    """True if the REAL literal has the same value in single and double precision."""
    x = float(lit.replace("D", "E").replace("Q", "E"))
    return struct.unpack("f", struct.pack("f", x))[0] == x


def parse_entity(ent: str) -> tuple[str, list[str] | None, str | None]:
    """`NAME(d1,d2)` / `NAME*80` -> (name, dims, char_len)."""
    m = re.match(r"^([A-Z][A-Z0-9_]*)\s*(?:\*\s*(\d+))?\s*(\((.*)\))?\s*$", ent)
    if not m:
        return ent.strip(), None, None
    dims = split_top_level(m.group(4)) if m.group(3) else None
    return m.group(1), dims, m.group(2)


def canonical_type(spec: str) -> str:
    spec = re.sub(r"\s+", "", spec)
    if spec in ("DOUBLEPRECISION", "REAL*8"):
        return "REAL*8"
    if spec in ("REAL", "REAL*4"):
        return "REAL"
    if spec.startswith("INTEGER"):
        return "INTEGER"
    if spec.startswith("LOGICAL"):
        return "LOGICAL"
    if spec.startswith("COMPLEX"):
        return "COMPLEX"
    return spec  # CHARACTER*n


# ---------------------------------------------------------------------------
# Program units
# ---------------------------------------------------------------------------


@dataclass
class Symbol:
    name: str
    type: str
    typing: str  # "explicit" | "implicit"
    role: str  # "dummy" | "local" | "parameter" | "common:/NAME/" | "result"
    dims: list[str] | None = None
    intent: str | None = None  # dummies only: in | out | inout | passed | unused
    value: str | None = None  # parameters only
    rust_type: str | None = None


@dataclass
class Unit:
    name: str
    kind: str
    line_start: int
    line_end: int = 0
    args: list[str] = field(default_factory=list)
    signature: str = ""
    includes: list[str] = field(default_factory=list)
    implicit: dict[str, str] = field(default_factory=dict)  # letter -> type ("" = NONE)
    symbols: dict[str, Symbol] = field(default_factory=dict)
    common_blocks: list[dict] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)
    labels: dict[int, int] = field(default_factory=dict)
    gotos: list[dict] = field(default_factory=list)
    do_loops: list[dict] = field(default_factory=list)
    hazards: list[dict] = field(default_factory=list)
    statements: list[Statement] = field(default_factory=list)
    events: list[tuple[int, str, str]] = field(default_factory=list)  # (line, name, read|write|pass)
    assigned: set[str] = field(default_factory=set)


def default_implicit() -> dict[str, str]:
    return {chr(c): ("INTEGER" if "I" <= chr(c) <= "N" else "REAL") for c in range(ord("A"), ord("Z") + 1)}


def apply_implicit(unit: Unit, norm: str) -> None:
    body = norm[len("IMPLICIT"):].strip()
    if body == "NONE":
        unit.implicit = {k: "" for k in unit.implicit}
        return
    for m in re.finditer(r"([A-Z][A-Z0-9\s*]*?)\s*\(([^)]*)\)", body):
        typ = canonical_type(m.group(1))
        for rng in m.group(2).split(","):
            rng = rng.strip()
            if "-" in rng:
                a, b = (x.strip() for x in rng.split("-", 1))
            else:
                a = b = rng
            for c in range(ord(a), ord(b) + 1):
                unit.implicit[chr(c)] = typ


def hazard(severity: str, code: str, line: int, message: str) -> dict:
    return {"severity": severity, "code": code, "line": line, "message": message}


class Analyzer:
    def __init__(self, path: Path, include_dirs: list[Path] | None = None):
        self.path = Path(path)
        self.raw = self.path.read_bytes()
        self.text = self.raw.decode("latin-1")
        self.include_dirs = [self.path.parent] + list(include_dirs or [])
        self.lines = [classify_line(i + 1, l) for i, l in enumerate(self.text.splitlines())]
        self.statements = logical_statements(self.lines)
        self.units: list[Unit] = []
        self.file_hazards: list[dict] = []
        self.includes_resolved: dict[str, str] = {}

    # -- include handling -------------------------------------------------
    def include_text(self, name: str) -> tuple[str, str]:
        for d in self.include_dirs:
            p = d / name
            if p.is_file():
                return p.read_text("latin-1"), str(p)
        if name.upper() in KNOWN_INCLUDES:
            return KNOWN_INCLUDES[name.upper()], "builtin stand-in (Abaqus ABA_PARAM.INC)"
        return "", "not found"

    # -- driver -------------------------------------------------------------
    def run(self) -> "Analyzer":
        for ln in self.lines:
            if ln.kind == "code" and ln.past_col72:
                self.file_hazards.append(hazard(
                    "warning", "CODE_PAST_COL72", ln.lineno,
                    f"code in columns 73+ is ignored by the compiler: {ln.past_col72!r}"))
        unit: Unit | None = None
        for st in self.statements:
            m = UNIT_RE.match(st.norm)
            if m and unit is None:
                unit = Unit(name=m.group("name"), kind=m.group("kind"), line_start=st.line_start)
                unit.args = [a.strip() for a in (m.group("args") or "").split(",") if a.strip()]
                unit.signature = st.norm
                unit.implicit = default_implicit()
                if m.group("kind") == "FUNCTION" and m.group("rtype"):
                    unit.symbols[unit.name] = Symbol(unit.name, canonical_type(m.group("rtype")),
                                                     "explicit", "result")
                continue
            if END_RE.match(st.norm):
                if unit is None:
                    self.file_hazards.append(hazard(
                        "warning", "STRAY_END", st.line_start,
                        "END statement outside any program unit (ignored by most compilers, "
                        "rejected by some)"))
                else:
                    unit.line_end = st.line_end
                    self.finish_unit(unit)
                    self.units.append(unit)
                    unit = None
                continue
            if unit is None:
                if st.norm:
                    self.file_hazards.append(hazard("warning", "STATEMENT_OUTSIDE_UNIT",
                                                    st.line_start, st.norm))
                continue
            unit.statements.append(st)
            self.statement(unit, st, st.norm)
        if unit is not None:
            unit.line_end = self.statements[-1].line_end
            unit.hazards.append(hazard("error", "MISSING_END", unit.line_start,
                                       f"{unit.kind} {unit.name} has no END"))
            self.finish_unit(unit)
            self.units.append(unit)
        return self

    # -- statements ---------------------------------------------------------
    def declare(self, unit: Unit, name: str, typ: str | None, dims: list[str] | None) -> None:
        sym = unit.symbols.get(name)
        if sym is None:
            sym = Symbol(name, typ or "", "explicit" if typ else "implicit", "local")
            unit.symbols[name] = sym
        if typ:
            sym.type, sym.typing = typ, "explicit"
        if dims:
            sym.dims = dims

    def statement(self, unit: Unit, st: Statement, s: str, nested: bool = False) -> None:
        line = st.line_start
        if st.label is not None and not nested:
            unit.labels[st.label] = line

        m = re.match(r"^INCLUDE\s*'([^']+)'$", s)
        if m:
            name = m.group(1)
            unit.includes.append(name)
            text, where = self.include_text(name)
            self.includes_resolved[name] = where
            for inc in logical_statements([classify_line(0, l) for l in text.splitlines()]):
                self.statement(unit, Statement(line, line, None, inc.text, inc.norm), inc.norm, True)
            return
        if s.startswith("IMPLICIT"):
            apply_implicit(unit, s)
            return
        m = re.match(r"^PARAMETER\s*\((.*)\)$", s)
        if m:
            for item in split_top_level(m.group(1)):
                if "=" in item:
                    name, value = (x.strip() for x in item.split("=", 1))
                    self.declare(unit, name, None, None)
                    unit.symbols[name].role = "parameter"
                    unit.symbols[name].value = value
                    self.check_literals(unit, line, value)
            return
        m = re.match(r"^DIMENSION\s*(.*)$", s)
        if m and not re.match(r"^DIMENSION\s*\(.*\)\s*=", s):
            for ent in split_top_level(m.group(1)):
                name, dims, _ = parse_entity(ent)
                self.declare(unit, name, None, dims)
            return
        m = re.match(r"^COMMON\s*(.*)$", s)
        if m:
            body = m.group(1)
            if not body.startswith("/"):
                body = "// " + body
            for bm in re.finditer(r"/\s*([A-Z0-9_]*)\s*/([^/]*)", body):
                block = bm.group(1) or ""
                members = []
                for ent in split_top_level(bm.group(2)):
                    name, dims, _ = parse_entity(ent)
                    self.declare(unit, name, None, dims)
                    unit.symbols[name].role = f"common:/{block}/"
                    members.append(name)
                unit.common_blocks.append({"name": block, "line": line, "members": members})
            return
        m = TYPE_RE.match(s)
        if m and not re.match(r"^[A-Z][A-Z0-9_]*\s*(\(.*?\))?\s*=", s):
            spec = m.group(1)
            rest = s[m.end():].strip()
            if rest.startswith(","):
                rest = rest[1:]
            base = canonical_type(spec)
            for ent in split_top_level(rest):
                name, dims, clen = parse_entity(ent)
                typ = f"CHARACTER*{clen}" if clen else base
                self.declare(unit, name, typ, dims)
                for d in dims or []:
                    self.reads(unit, line, d)
            return
        if re.match(r"^(SAVE|EXTERNAL|INTRINSIC|DATA|FORMAT|EQUIVALENCE)\b", s):
            return

        # Control flow -------------------------------------------------------
        m = re.match(r"^(?:ELSE\s*)?IF\s*\(", s)
        if m:
            open_idx = s.index("(", m.start())
            close_idx = match_paren(s, open_idx)
            cond, tail = s[open_idx + 1:close_idx], s[close_idx + 1:].strip()
            self.reads(unit, line, cond)
            self.check_logical_ops(unit, line, cond)
            self.check_literals(unit, line, cond)
            arith = re.match(r"^(\d+)\s*,\s*(\d+)\s*,\s*(\d+)$", tail)
            if arith:
                for lbl in arith.groups():
                    unit.gotos.append({"line": line, "label": int(lbl), "kind": "arithmetic_if"})
            elif tail and tail != "THEN":
                self.statement(unit, st, tail, True)
            return
        m = re.match(r"^GO\s*TO\s*(\d+)$", s)
        if m:
            unit.gotos.append({"line": line, "label": int(m.group(1)), "kind": "unconditional"})
            return
        m = re.match(r"^GO\s*TO\s*\(([\d,\s]+)\)\s*,?\s*(.*)$", s)
        if m:
            for lbl in m.group(1).split(","):
                unit.gotos.append({"line": line, "label": int(lbl), "kind": "computed"})
            self.reads(unit, line, m.group(2))
            return
        m = re.match(r"^DO\s*(\d+)?\s*,?\s*([A-Z][A-Z0-9_]*)\s*=\s*(.+)$", s)
        if m and "," in m.group(3):
            var = m.group(2)
            unit.do_loops.append({"line": line, "var": var,
                                  "label": int(m.group(1)) if m.group(1) else None,
                                  "bounds": m.group(3)})
            self.writes(unit, line, var, do_var=True)
            self.reads(unit, line, m.group(3))
            return
        m = re.match(r"^CALL\s*([A-Z][A-Z0-9_]*)\s*(.*)$", s)
        if m:
            name, rest = m.group(1), m.group(2).strip()
            args: list[str] = []
            valid = not rest or rest.startswith("(")
            if not valid:
                unit.hazards.append(hazard(
                    "error", "INVALID_CALL_NAME", line,
                    f"`CALL {name}{rest}` is not valid Fortran: '{rest[0]}' cannot follow a "
                    f"subroutine name (did the author mean {name}_{rest.lstrip('-+*/').split('(')[0]}?)"))
            elif rest.startswith("("):
                close_idx = match_paren(rest, 0)
                args = split_top_level(rest[1:close_idx])
            unit.calls.append({"name": name, "line": line, "args": args, "valid": valid})
            for a in args:
                for n in names_in(a):
                    unit.events.append((line, n, "pass"))
            return
        if re.match(r"^(RETURN|CONTINUE|STOP|ELSE|END\s*IF|END\s*DO|PAUSE)\b", s):
            return
        m = re.match(r"^([A-Z][A-Z0-9_]*)\s*(\((.*?)\))?\s*=(?!=)(.*)$", s)
        if m:
            self.reads(unit, line, m.group(4))
            if m.group(3):
                self.reads(unit, line, m.group(3))
            self.writes(unit, line, m.group(1))
            self.check_logical_ops(unit, line, m.group(4))
            self.check_literals(unit, line, m.group(4))
            return
        self.reads(unit, line, s)

    def reads(self, unit: Unit, line: int, expr: str) -> None:
        for n in names_in(expr):
            unit.events.append((line, n, "read"))

    def writes(self, unit: Unit, line: int, name: str, do_var: bool = False) -> None:
        unit.events.append((line, name, "write"))
        if not do_var:
            unit.assigned.add(name)

    def check_logical_ops(self, unit: Unit, line: int, expr: str) -> None:
        for m in re.finditer(r"\(\s*[+-]?\d+\s*\.(AND|OR)\.\s*[+-]?\d+\s*\)", expr):
            unit.hazards.append(hazard(
                "error", "LOGICAL_OP_ON_INTEGERS", line,
                f"`{m.group(0)}` applies .{m.group(1)}. to INTEGER operands; F77 requires "
                f"LOGICAL operands (probably meant `X.EQ.a .OR. X.EQ.b`)"))

    def check_literals(self, unit: Unit, line: int, expr: str) -> None:
        if unit.implicit.get("A") != "REAL*8":
            return
        singles = [lit for lit, prec in real_literals(expr)
                   if prec == "REAL" and not f32_exact(lit)]
        if singles:
            unit.hazards.append(hazard(
                "info", "SINGLE_PRECISION_LITERAL", line,
                f"REAL (f32) literal(s) {', '.join(singles)} in a REAL*8 unit: rounded to single "
                f"precision before promotion; the Rust port must use `{singles[0]}_f32 as f64`"))

    # -- per-unit post-processing ------------------------------------------
    def finish_unit(self, u: Unit) -> None:
        callees = {c["name"] for c in u.calls}  # incl. invalid ones, so they are not symbols
        referenced = {n for _, n, _ in u.events}
        for n in sorted(referenced | set(u.args)):
            if n in callees or n == u.name and u.kind == "SUBROUTINE":
                continue
            if n not in u.symbols:
                if n in F77_INTRINSICS and n not in u.args:
                    continue  # intrinsic function reference
                u.symbols[n] = Symbol(n, "", "implicit", "local")
        for n, sym in u.symbols.items():
            if not sym.type:
                sym.type = u.implicit.get(n[0], "")
                if not sym.type:
                    u.hazards.append(hazard("error", "UNTYPED_UNDER_IMPLICIT_NONE",
                                            u.line_start, f"{n} has no type"))
            if n in u.args:
                sym.role = "dummy"
        # intents
        for a in u.args:
            evs = [k for _, n, k in u.events if n == a]
            sym = u.symbols[a]
            if not evs:
                sym.intent = "unused"
            elif "write" in evs:
                sym.intent = "out" if evs[0] == "write" else "inout"
            elif "read" in evs:
                sym.intent = "in"
            else:
                sym.intent = "passed"  # only handed to CALLs; callee decides
        # Rust type hints
        for sym in u.symbols.values():
            base = RUST_TYPES.get(sym.type) or (
                f"[u8; {sym.type.split('*')[1]}]" if sym.type.startswith("CHARACTER*") else None)
            if base and sym.dims:
                ref = "&mut " if sym.intent in ("out", "inout") else "&"
                layout = ", column-major" if len(sym.dims) > 1 else ""
                base = f"{ref}[{base}] /* {'x'.join(sym.dims)}{layout} */"
            elif base and sym.intent in ("out", "inout"):
                base = f"&mut {base}"
            sym.rust_type = base
        # gotos
        for g in u.gotos:
            tgt = u.labels.get(g["label"])
            g["target_line"] = tgt
            if tgt is None:
                u.hazards.append(hazard("error", "UNDEFINED_LABEL", g["line"],
                                        f"GO TO {g['label']}: label not defined in {u.name}"))
                g["direction"] = "unknown"
                continue
            g["direction"] = "backward" if tgt < g["line"] else "forward"
            if g["direction"] == "backward":
                u.hazards.append(hazard(
                    "info", "BACKWARD_GOTO", g["line"],
                    f"GO TO {g['label']} jumps back to line {tgt}: an implicit loop to restructure "
                    f"as `loop`/`for` (see f77-semantics.md, GOTO elimination)"))
        # DO variable reused as state inside a GO TO loop region
        for g in u.gotos:
            if g.get("direction") != "backward":
                continue
            lo, hi = g["target_line"], g["line"]
            for d in u.do_loops:
                # Carried = read inside the region before any write to it in the region,
                # i.e. its value flows in from the previous trip around the GO TO loop.
                region = sorted((ln, k) for ln, n, k in u.events
                                if n == d["var"] and lo <= ln < d["line"])
                carried = bool(region) and region[0][1] == "read"
                if lo <= d["line"] <= hi and d["var"] in u.assigned and carried:
                    u.hazards.append(hazard(
                        "warning", "DO_VAR_REUSED_IN_GOTO_LOOP", d["line"],
                        f"DO variable {d['var']} also carries state across the GO TO {g['label']} "
                        f"loop (lines {lo}-{hi}): it is read after label {g['label']} and then "
                        f"clobbered by this DO loop, so the translation must keep the two uses as "
                        f"separate variables"))
        # intrinsic shadowing, automatic arrays
        if u.name in F77_INTRINSICS | F90_INTRINSICS:
            u.hazards.append(hazard(
                "warning", "INTRINSIC_SHADOWED", u.line_start,
                f"{u.kind} {u.name} has the name of a Fortran intrinsic; compiled as an external "
                f"by F77 rules but a hazard for modern compilers and readers"))
        for n, sym in u.symbols.items():
            if sym.dims and n in F77_INTRINSICS | F90_INTRINSICS:
                u.hazards.append(hazard(
                    "warning", "INTRINSIC_SHADOWED", u.line_start,
                    f"array {n} hides the intrinsic function {n} inside {u.name}"))
            if sym.dims and sym.role == "local" and any(
                    set(names_in(d)) & set(u.args) for d in sym.dims):
                u.hazards.append(hazard(
                    "info", "AUTOMATIC_ARRAY", u.line_start,
                    f"local array {n}({','.join(sym.dims)}) is sized by dummy arguments: an "
                    f"automatic array (not standard F77); use a Vec or fixed max size in Rust"))
        u.hazards.sort(key=lambda h: (h["line"], h["code"]))

    # -- whole-file views ---------------------------------------------------
    def call_graph(self) -> dict[str, list[str]]:
        return {u.name: sorted({c["name"] for c in u.calls if c["valid"]}) for u in self.units}

    def schedule(self) -> list[str]:
        """Leaves-first order over the CALL graph (callees before callers)."""
        defined = {u.name for u in self.units}
        graph = {k: [c for c in v if c in defined] for k, v in self.call_graph().items()}
        order, state = [], {}

        def visit(n: str, stack: list[str]) -> None:
            if state.get(n) == "done":
                return
            if state.get(n) == "active":
                self.file_hazards.append(hazard("warning", "RECURSIVE_CALL", 0,
                                                " -> ".join(stack + [n])))
                return
            state[n] = "active"
            for c in graph[n]:
                visit(c, stack + [n])
            state[n] = "done"
            order.append(n)

        # Visit leaves first (in source order), then everything else.
        for u in sorted(self.units, key=lambda u: (len(graph[u.name]) > 0, u.line_start)):
            visit(u.name, [])
        return order

    def to_spec(self, source_label: str | None = None) -> dict:
        crlf = b"\r\n" in self.raw
        defined = {u.name for u in self.units}
        graph = self.call_graph()
        units = []
        for u in self.units:
            units.append({
                "name": u.name,
                "kind": u.kind,
                "line_start": u.line_start,
                "line_end": u.line_end,
                "signature": u.signature,
                "args": [asdict(u.symbols[a]) for a in u.args],
                "includes": u.includes,
                "implicit_rules": implicit_summary(u.implicit),
                "symbols": [asdict(s) for s in sorted(u.symbols.values(), key=lambda s: s.name)
                            if s.role != "dummy"],
                "common_blocks": u.common_blocks,
                "calls": u.calls,
                "labels": {str(k): v for k, v in sorted(u.labels.items())},
                "gotos": u.gotos,
                "do_loops": u.do_loops,
                "hazards": u.hazards,
                "statement_count": len(u.statements),
                "acceptance": acceptance(u),
            })
        all_hazards = self.file_hazards + [h | {"unit": u.name} for u in self.units for h in u.hazards]
        return {
            "schema": SCHEMA,
            "source": {
                "path": source_label or str(self.path),
                "sha256": hashlib.sha256(self.raw).hexdigest(),
                "bytes": len(self.raw),
                "lines": len(self.lines),
                "line_endings": "CRLF" if crlf else "LF",
                "comment_lines": sum(1 for l in self.lines if l.kind == "comment"),
                "code_lines": sum(1 for l in self.lines if l.kind == "code"),
            },
            "fixed_form": {"label_cols": "1-5", "continuation_col": 6,
                           "statement_cols": "7-72", "ignored_cols": "73-80"},
            "includes_resolved": self.includes_resolved,
            "units": units,
            "call_graph": graph,
            "externals": sorted({c for v in graph.values() for c in v} - defined),
            "schedule": self.schedule(),
            "file_hazards": self.file_hazards,
            "summary": {
                "units": len(self.units),
                "gotos": sum(len(u.gotos) for u in self.units),
                "backward_gotos": sum(1 for u in self.units for g in u.gotos
                                      if g.get("direction") == "backward"),
                "common_blocks": sum(len(u.common_blocks) for u in self.units),
                "hazards": {sev: sum(1 for h in all_hazards if h["severity"] == sev)
                            for sev in ("error", "warning", "info")},
                "units_with_errors": sorted({h["unit"] for h in all_hazards
                                             if h["severity"] == "error" and "unit" in h}),
            },
        }


def implicit_summary(implicit: dict[str, str]) -> list[str]:
    """{'A': 'REAL*8', ...} -> ['A-H: REAL*8', 'I-N: INTEGER', 'O-Z: REAL*8']."""
    out, letters = [], sorted(implicit)
    i = 0
    while i < len(letters):
        j = i
        while j + 1 < len(letters) and implicit[letters[j + 1]] == implicit[letters[i]]:
            j += 1
        rng = letters[i] if i == j else f"{letters[i]}-{letters[j]}"
        out.append(f"{rng}: {implicit[letters[i]] or 'NONE'}")
        i = j + 1
    return out


def acceptance(u: Unit) -> list[str]:
    """EARS-style acceptance criteria for resurrecting this unit."""
    outs = [a for a in u.args if u.symbols[a].intent in ("out", "inout")]
    crit = [
        f"WHEN the Rust port of {u.name} is called with bounded finite inputs THEN it SHALL "
        f"match the gfortran -std=legacy oracle on {', '.join(outs) or 'its result'} for at "
        f"least 1,024 proptest cases.",
    ]
    for a in u.args:
        s = u.symbols[a]
        if s.dims and any(set(names_in(d)) & set(u.args) for d in s.dims):
            crit.append(f"IF {a}({','.join(s.dims)}) is shorter than its declared size THEN the "
                        f"Rust port SHALL return an error instead of accessing it out of bounds.")
    for g in u.gotos:
        if g.get("direction") == "backward":
            crit.append(f"The GO TO {g['label']} loop (lines {g['target_line']}-{g['line']}) SHALL "
                        f"be replaced by structured control flow with the label documented.")
    for cb in u.common_blocks:
        crit.append(f"COMMON /{cb['name']}/ SHALL be modelled as an explicit struct passed as &mut.")
    if any(u.symbols[a].intent == "inout" for a in u.args):
        crit.append("In/out arguments SHALL be grouped into an explicit `&mut State` struct; no "
                    "globals.")
    for h in u.hazards:
        if h["severity"] == "error":
            crit.append(f"The hazard {h['code']} at line {h['line']} SHALL be resolved or the unit "
                        f"SHALL stay out of scope.")
    return crit


# ---------------------------------------------------------------------------
# Extraction (used by the oracle gate)
# ---------------------------------------------------------------------------


def extract_units(text: str, names: list[str]) -> str:
    """Verbatim fixed-form source of the named units (LF line endings)."""
    lines = text.splitlines()
    sls = [classify_line(i + 1, l) for i, l in enumerate(lines)]
    stmts = logical_statements(sls)
    out: list[str] = []
    for name in names:
        start = None
        for st in stmts:
            m = UNIT_RE.match(st.norm)
            if start is None and m and m.group("name") == name:
                start = st.line_start
            elif start is not None and END_RE.match(st.norm):
                out.extend(lines[start - 1:st.line_end])
                break
        else:
            raise KeyError(f"unit {name} not found (or has no END)")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def to_markdown(spec: dict) -> str:
    src = spec["source"]
    md = [
        f"# Kiro Spec (generated): `{src['path']}`",
        "",
        f"Generated by `orchestrator/f77_analyzer.py` ({spec['schema']}). Source sha256 "
        f"`{src['sha256'][:16]}...`, {src['lines']} lines ({src['line_endings']}), "
        f"{src['code_lines']} code / {src['comment_lines']} comment lines.",
        "",
        "Fixed form: labels in columns 1-5, continuation in column 6, statements in "
        "columns 7-72, columns 73-80 ignored.",
        "",
        "## Schedule (leaves first)",
        "",
        " -> ".join(f"`{n}`" for n in spec["schedule"]),
        "",
        "## Call graph",
        "",
    ]
    for k, v in spec["call_graph"].items():
        md.append(f"- `{k}` -> {', '.join(f'`{c}`' for c in v) if v else '(leaf)'}")
    if spec["externals"]:
        md += ["", f"Externals: {', '.join(spec['externals'])}"]
    if spec["file_hazards"]:
        md += ["", "## File-level hazards", ""]
        md += [f"- **{h['severity']}** `{h['code']}` line {h['line']}: {h['message']}"
               for h in spec["file_hazards"]]
    for u in spec["units"]:
        md += ["", f"## {u['kind']} `{u['name']}` (lines {u['line_start']}-{u['line_end']})", "",
               f"`{u['signature']}`", ""]
        if u["includes"]:
            md.append(f"Includes: {', '.join(u['includes'])}. ")
        md.append(f"Implicit typing: {'; '.join(u['implicit_rules'])}.")
        if u["args"]:
            md += ["", "| Argument | Type | Typing | Dims | Intent | Rust |",
                   "|---|---|---|---|---|---|"]
            for a in u["args"]:
                dims = ",".join(a["dims"]) if a["dims"] else ""
                md.append(f"| `{a['name']}` | {a['type']} | {a['typing']} | {dims} | "
                          f"{a['intent']} | `{a['rust_type']}` |")
        implicit_locals = [s["name"] for s in u["symbols"]
                           if s["typing"] == "implicit" and s["role"] == "local"]
        if implicit_locals:
            md += ["", f"Implicitly typed locals: {', '.join(f'`{n}`' for n in implicit_locals)}"]
        if u["common_blocks"]:
            md += ["", "COMMON blocks: " + "; ".join(
                f"/{c['name']}/ {', '.join(c['members'])}" for c in u["common_blocks"])]
        else:
            md += ["", "COMMON blocks: none."]
        if u["calls"]:
            md += ["", "Calls: " + ", ".join(f"`{c['name']}` (line {c['line']})" for c in u["calls"])]
        if u["gotos"]:
            md += ["", "| GO TO | From line | Target line | Direction |", "|---|---|---|---|"]
            for g in u["gotos"]:
                md.append(f"| {g['label']} | {g['line']} | {g.get('target_line')} | "
                          f"{g.get('direction')} |")
        if u["hazards"]:
            md += ["", "Hazards:", ""]
            md += [f"- **{h['severity']}** `{h['code']}` line {h['line']}: {h['message']}"
                   for h in u["hazards"]]
        md += ["", "Acceptance criteria:", ""]
        md += [f"{i}. {c}" for i, c in enumerate(u["acceptance"], 1)]
    return "\n".join(md) + "\n"


def analyze(path: Path, include_dirs: list[Path] | None = None,
            source_label: str | None = None) -> dict:
    return Analyzer(path, include_dirs).run().to_spec(source_label)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("source", type=Path)
    ap.add_argument("--json", type=Path, help="write the spec as JSON here")
    ap.add_argument("--md", type=Path, help="write the spec as Markdown here")
    ap.add_argument("-I", "--include-dir", type=Path, action="append", default=[])
    args = ap.parse_args(argv)
    spec = analyze(args.source, args.include_dir)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(spec, indent=2) + "\n")
    if args.md:
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text(to_markdown(spec))
    if not args.json and not args.md:
        json.dump(spec, sys.stdout, indent=2)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
