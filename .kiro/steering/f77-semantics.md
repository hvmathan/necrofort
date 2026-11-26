---
inclusion: always
---

# Fortran 77 Semantics (read before translating any `.f` / `.FOR` file)

Translations must preserve the observable behaviour of the original code exactly,
including its quirks. When the source does something surprising, keep the
behaviour, add a `// F77:` comment explaining it, and cover it in the
differential test. Never "fix" upstream code silently.

## Fixed-form source layout

| Columns | Meaning |
|---------|---------|
| 1       | `C`, `c`, `*` (or `!`) marks the whole line as a comment |
| 1-5     | Optional numeric statement label (e.g. `80`, `90` used as `GO TO` targets) |
| 6       | Continuation marker: any character other than blank or `0` continues the previous statement |
| 7-72    | Statement text |
| 73-80   | Ignored by the compiler (historically card sequence numbers). Code past column 72 is silently dropped |

- Blanks are not significant in F77 (`GO TO` == `GOTO`, `DO 10 I` == `DO10I`).
- Keywords and identifiers are case-insensitive. gfortran lowercases external
  symbols and appends one underscore: `SUBROUTINE VMATMUL` links as `vmatmul_`.
- Inline `!` comments are a common vendor extension (accepted by `gfortran -std=legacy`).
- Watch for continuation lines that carry operators (`1 *DFGRD(i,K1)`); join them
  before reasoning about operator precedence.

## Implicit typing

- Unless declared otherwise, names starting with `I`-`N` are `INTEGER`; all others are `REAL`.
- `IMPLICIT REAL*8(A-H,O-Z)` (e.g. Abaqus `ABA_PARAM.INC`) promotes the non-integer
  range to `DOUBLE PRECISION` (`f64`). Check every `INCLUDE` before choosing a Rust type.
- Mixed-mode expressions promote (`INTEGER` -> `REAL` -> `DOUBLE PRECISION`). Single
  precision literals (`1.4`, `0.59`) stay `REAL` (`f32`) until promoted; model this
  explicitly with `f32` literals cast to `f64` when it affects results.
- Assigning a `REAL` to an `INTEGER` truncates toward zero (`INT`), not rounding.

## Arrays

- Indexing is 1-based by default; `DIMENSION A(0:N)` changes the lower bound.
- Storage is column-major: `A(i,j)` for `A(3,3)` lives at linear offset
  `(i-1) + 3*(j-1)`. Rust code keeps the flat column-major buffer and uses an
  accessor (`at(a, i, j)`) that accepts 1-based indices so formulas read like the source.
- Arrays are passed by reference with no bounds information. A dummy declared
  `C(N)` may be larger or smaller than the actual argument; out-of-bounds writes
  are undefined behaviour in the original. Rust must reject such inputs with an
  error instead of reproducing memory corruption.
- All scalar arguments are passed by reference, so a subroutine may mutate its
  inputs (e.g. UMAT perturbs `DFGRD1` in place). Model this with `&mut`.

## COMMON blocks and SAVE

- `COMMON /NAME/ A, B` is shared global storage laid out by position, not by name.
  Different routines may view the same block with different variable names/types.
- Locals without `SAVE` are not guaranteed to persist, but many legacy codes rely
  on static allocation. Treat persisted locals as part of the state.
- Rust replacement: one explicit `struct` per COMMON block (or per SAVE set),
  passed as `&mut State`. No `static mut`, no globals.

## Control flow and GOTO elimination

- `DO 10 I = 1, N` executes zero times if `N < 1`; the trip count is computed once
  on entry. The loop variable after normal exit is `N + 1`.
- Arithmetic IF `IF (X) 10, 20, 30` branches on negative / zero / positive.
- Eliminate `GO TO` by structure, in this order of preference:
  1. Backward jumps that re-enter a block (e.g. UMAT `GO TO 80` / `GO TO 90`
     perturbation loop) become `loop { ... }` with explicit `break`/`continue`.
  2. Forward jumps that skip code become `if` / early `return`.
  3. Computed `GO TO` becomes `match`.
  4. Irreducible spaghetti becomes a `loop { match state { ... } }` state machine.
- Document the original labels next to the replacement (`// F77 label 80`).

## Floating point

- Preserve evaluation order: F77 `A*B + C*D + E*F` is `((A*B) + (C*D)) + (E*F)`.
  Do not refactor into iterator sums or reorder terms.
- The oracle is compiled with `-ffp-contract=off` so neither side fuses multiply-add.
- `X**TWO` with a `DOUBLE PRECISION` exponent is a real power (`pow`), while `X**2`
  (integer exponent) is repeated multiplication. Mirror the exponent type
  (`powf` vs `powi`) and let the differential test confirm the result.
