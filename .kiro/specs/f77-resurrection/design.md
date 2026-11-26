# Design: F77 Resurrection

## Overview

```
targets/bioumat/SUBROUTINES.FOR   (upstream, untouched, CRLF preserved)
          |
          | build.rs: extract routines verbatim -> $OUT_DIR/bioumat_kernels.f
          | gfortran -std=legacy -ffp-contract=off -O2 -fPIC -c
          | ar crs libbioumat_oracle.a     (linked into test binaries only)
          v
oracle-harness/
  src/lib.rs                 #![forbid(unsafe_code)] resurrected routines + #[wasm_bindgen]
  tests/differential_pbt.rs  extern "C" oracle bindings (only unsafe in repo) + proptest
          |
          | wasm-pack build --target web
          v
oracle-harness/pkg/          -> consumed by web-demo/ (Phase 2)

orchestrator/ (Phase 2)      drives: parse -> schedule -> translate -> gate -> report
```

## Target analysis: BioUMAT

Line 463 of the upstream file is a stray `END` with no program unit.

| Routine | Lines | Role | `-std=legacy` | Notes |
|---------|-------|------|---------------|-------|
| `SDVINI` | 9-99 | State variable init | fails | `CALL RANDOM-NUMBER` syntax error; `STATEV(1).EQ.(5.OR.6)` integer `.OR.`; reads `STATEV(10)` before it is set |
| `FLOW` | 104-116 | Pore-flow BC | ok (with `ABA_PARAM.INC`) | trivial |
| `UMAT` | 122-392 | Constitutive model | ok (with `ABA_PARAM.INC`) | `GO TO 80/90` perturbation loop for the Jacobian; mutates `DFGRD1` and `STATEV` |
| `TRANSPOSE` | 400-409 | 3x3 transpose | ok | name shadows the F90 intrinsic |
| `DETERMINANT` | 413-419 | 3x3 determinant | ok | |
| `VMATMUL` | 423-435 | `A*B` in Voigt order | ok | writes `C(1..4)`, plus `C(5..6)` only when `N == 6` |
| `TENF` | 439-461 | Voigt vector -> 3x3 tensor | ok | |

Because `SDVINI` does not compile, `build.rs` extracts only the routines under
test instead of compiling the whole file. The extractor scans fixed-form code
lines (skipping comment lines) for `SUBROUTINE <NAME>` and copies through the
matching `END`. A missing routine fails the build.

## Phase 1 routine: `VMATMUL`

Original contract (`SUBROUTINE VMATMUL(A,B,N,C)`):

- `A(3,3)`, `B(3,3)`: `DOUBLE PRECISION`, column-major, read-only.
- `N`: `INTEGER`, length of `C` (NTENS: 4 for plane/axisymmetric, 6 for 3D).
- `C(N)`: output, Voigt order `11, 22, 33, 12, 13, 23` of `A*B`.
- Writes `C(1..4)` always and `C(5), C(6)` only if `N == 6`. For `N < 4` it writes
  out of bounds (undefined behaviour). For `N = 5` or `N > 6`, entries after 4 are untouched.
- UMAT calls it as `VMATMUL(DFGRD1, TRANSPOSE(DFGRD1), NTENS, BVEC)` to form the
  left Cauchy-Green tensor `b = F F^T`.

Rust design:

```rust
pub type Mat3 = [f64; 9];                     // column-major, at(a, i, j) is 1-based
pub enum VoigtError { OutputTooShort { len }, BadMatrixLen { len } }
pub fn vmatmul(a: &Mat3, b: &Mat3, c: &mut [f64]) -> Result<(), VoigtError>;   // N = c.len()
#[wasm_bindgen(js_name = vmatmul)]
pub fn vmatmul_wasm(a: &[f64], b: &[f64], n: usize) -> Result<Vec<f64>, JsError>;
```

- `N` is taken from the slice length, so the Rust caller cannot pass a mismatched size.
- `c.len() < 4` returns `VoigtError::OutputTooShort` (the original would corrupt memory).
- Entries the original leaves untouched are left untouched in Rust too; the
  differential test fills `C` with a sentinel to check this.
- Products are summed in source order with no FMA, so results are expected to be
  bit-identical to the `-ffp-contract=off` oracle. The test still uses a rigorous bound
  `8 * EPS * sum_k |A(i,k)| * |B(k,j)|` so a legitimate compiler difference would not
  produce false failures.

## Differential test harness

- FFI: `extern "C" { fn vmatmul_(a: *const f64, b: *const f64, n: *const i32, c: *mut f64); }`.
  gfortran passes every argument by reference; Fortran default `INTEGER` is `i32`.
- Properties, each with `ProptestConfig::with_cases(1024)`:
  1. General `A`, `B` with entries in `[-1e3, 1e3]`, `N` in `4..=8`, sentinel-filled
     output: every entry of `C` matches the oracle (computed and untouched ones).
  2. UMAT usage: `F` near identity (`I + H`, `H` in `[-0.5, 0.5]`), `B = F^T`, `N` in `{4, 6}`:
     matches the oracle, and `C(1..3) >= 0` (diagonal of `F F^T`).
- Unit tests check identity input, the error path, and the wasm-facing pure wrapper.

## Error handling

- Library: `Result` with a small error enum implementing `Display` and `std::error::Error`.
- Wasm: errors are mapped to `JsError` with the `Display` message.
- `build.rs`: panics with the gfortran command and stderr if compilation fails, or
  with a hint to install gfortran if it is missing.

## Phase 2 routines: `TRANSPOSE`, `DETERMINANT`, `TENF`, `UMAT`

- `TRANSPOSE`, `DETERMINANT`, `TENF` are direct ports (`transpose`, `determinant`,
  `tenf`). `TENF` returns an error for `N < 4` (the original reads `V(4)` out of bounds).
- `UMAT` is ported as `umat(&Mat3, &mut UmatState)`. `UmatState { ntens, stress,
  ddsdde, statev }` holds the in/out Abaqus arrays explicitly (UMAT has no COMMON
  blocks; the by-reference arguments are its shared state).
- `GO TO 80/90` elimination: a `for` loop over `VOIGT_PAIRS[..ntens]` runs the NTENS
  perturbed passes (label 80 perturbs `DFGRD1`, label 90 resets `STRESS`/`STATEV`),
  followed by one unperturbed pass and the forward-difference finish. The DO-loop
  variable `i` that the original reuses as the perturbation index (analyzer hazard
  `DO_VAR_REUSED_IN_GOTO_LOOP`, line 277) is split into separate variables.
  `DFGRD1` is never mutated; the original perturbs it in place and restores it.
- Only the `DDS=1` branch is reachable (`DDS` is a hard-coded constant), so the dead
  exact-Jacobian branch is not ported.
- `build.rs` writes a minimal `ABA_PARAM.INC` (`IMPLICIT REAL*8(A-H,O-Z)`,
  `PARAMETER (NPRECD=2)`) into `$OUT_DIR` so `UMAT` compiles verbatim.
- Differential test: `F = I + H` with `det F` in `[0.5, 2.0]`, physically meaningful
  STATEV (type, RH, NS0, fibril direction, ALPHA1) plus filler that must stay
  untouched, NTENS in {4, 6}. Compares STRESS, DDSDDE, all of STATEV, and that the
  oracle restores DFGRD1. Results are bit-identical on every compared entry.

## Orchestrator (Phase 2)

Python 3 (standard library only), in `orchestrator/`:

- `f77_analyzer.py`: fixed-form lexer (cols 1-5 label, col 6 continuation, cols 7-72
  statement, cols 73-80 ignored, inline `!`), program units and signatures, explicit and
  implicit I-N typing (including `INCLUDE`d `IMPLICIT`), COMMON blocks, PARAMETERs,
  CALL graph, labels and GO TOs (unconditional, computed, arithmetic IF), DO loops,
  argument intents, hazards, leaves-first schedule. Emits `spec.json` + `spec.md`
  with EARS acceptance criteria per unit.
- `graph.py`: state machine `PARSE -> SPEC -> TRANSMUTE -> ORACLE_GATE -> (SELF_HEAL
  -> ORACLE_GATE)* -> PR -> DONE | BLOCKED` with an explicit transition table. Works in
  a copy of the crate under `orchestrator/.work/`, never in the repository.
  - ORACLE_GATE runs gfortran on the analyzer's extraction, `cargo test`, `cargo clippy
    --all-targets -D warnings`, `wasm-pack build --target web`, stopping at the first failure.
  - The differential suite reports failures as `NECRO_COUNTEREXAMPLE {json}` (routine,
    output entry, Rust and oracle values, shrunk inputs). SELF_HEAL passes only that
    to the healer. The built-in `IndexOffsetHealer` repairs off-by-one subscripts by
    matching the oracle value against the inputs and the `// F77:` annotation on the
    Rust line; other fault classes block with a report.
  - Hard cap of 5 heal attempts (`MAX_HEAL_ATTEMPTS`), then BLOCKED.
  - `--demo-bug` plants `v[5]` for `V(5)` in `tenf` (1-based subscript copied literally).
  - PR modes: `dry-run` (payload only), `open` (draft PR via `gh api`), `status`
    (records an existing PR).
  - `run_log.json` records transitions, timed steps, gate runs with output tails,
    planted bug, counterexamples, heals with diffs, parity counts, and PR status.

## Web demo (Phase 2)

React + Vite + Tailwind (`web-demo/`), static build:

- Tab 1, Graveyard & Swarm Dashboard: the untouched source with column zones, per-unit
  generated spec, the state graph replayed from `run_log.json`, the counterexample and
  heal, and the PR status (recorded, with optional live refresh from the GitHub API).
- Tab 2, Live WASM BioUMAT Lab: loads `oracle-harness/pkg` and runs `umat` for a
  slider-driven deformation gradient and depth-dependent cartilage STATEV; plots the
  stress components and `b = F F^T` over a stretch sweep, the DDSDDE heatmap, and a
  call benchmark.
- Build data is bundled at build time from `targets/`, `orchestrator/out/`, and
  `oracle-harness/pkg/` (run `wasm-pack build --target web` first).

## Testing strategy

| Level | Tool | Where |
|-------|------|-------|
| Oracle compile | gfortran `-std=legacy` | `oracle-harness/build.rs` |
| Unit | `cargo test` | `oracle-harness/src/lib.rs` |
| Differential PBT | `proptest` + FFI | `oracle-harness/tests/differential_pbt.rs` |
| Lint | `cargo clippy --all-targets -- -D warnings` | crate root |
| Wasm | `wasm-pack build --target web` | crate root |
| Orchestrator | `pytest orchestrator/tests` | `orchestrator/` |
| End-to-end | `python3 orchestrator/graph.py --demo-bug` | repo root |
| UI | `npm run build` | `web-demo/` |
