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

## Orchestrator (Phase 2)

- Rust binary crate `orchestrator/`.
- Fixed-form lexer: label/continuation/statement columns, comment lines, `INCLUDE`.
- Program-unit index: name, line range, arguments, `CALL` targets, `COMMON` blocks.
- Scheduler: topological order over the CALL graph, leaves first.
- Work item pipeline: write extraction entry -> draft Rust -> generate proptest from
  the argument signature -> run the 4-step gate -> record result in a JSON report.
- Retry cap of 5 per routine, enforced by the orchestrator, not by the agent.

## Web demo (Phase 2)

- `web-demo/index.html` + `main.js` importing `../oracle-harness/pkg/oracle_harness.js` via ES modules.
- Inputs: 3x3 deformation gradient grid, NTENS selector. Output: `b = F F^T` Voigt vector,
  determinant, and error messages.
- Served by any static file server; no bundler.

## Testing strategy

| Level | Tool | Where |
|-------|------|-------|
| Oracle compile | gfortran `-std=legacy` | `oracle-harness/build.rs` |
| Unit | `cargo test` | `oracle-harness/src/lib.rs` |
| Differential PBT | `proptest` + FFI | `oracle-harness/tests/differential_pbt.rs` |
| Lint | `cargo clippy --all-targets -- -D warnings` | crate root |
| Wasm | `wasm-pack build --target web` | crate root |
