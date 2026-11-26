#![forbid(unsafe_code)]
//! Safe Rust + WebAssembly resurrections of Fortran 77 kernels from BioUMAT
//! (`targets/bioumat/SUBROUTINES.FOR`, MIT, (c) 2019 Seyed Shayan Sajjadinia).
//!
//! Every routine here is checked against the gfortran-compiled original in
//! `tests/differential_pbt.rs`.

use std::fmt;
use wasm_bindgen::prelude::*;

/// A 3x3 `DOUBLE PRECISION` matrix in Fortran column-major order:
/// `A(i,j)` is stored at `[(i-1) + 3*(j-1)]`.
pub type Mat3 = [f64; 9];

/// Voigt length for plane-strain / axisymmetric elements (Abaqus `NTENS = 4`).
pub const NTENS_PLANE: usize = 4;
/// Voigt length for 3D solid elements (Abaqus `NTENS = 6`).
pub const NTENS_SOLID: usize = 6;

/// Errors for inputs the original Fortran would mishandle.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum VoigtError {
    /// The output vector is shorter than the 4 entries `VMATMUL` always writes.
    /// In the F77 original this is an out-of-bounds write.
    OutputTooShort { len: usize },
    /// A matrix argument did not have exactly 9 elements.
    BadMatrixLen { len: usize },
}

impl fmt::Display for VoigtError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::OutputTooShort { len } => write!(
                f,
                "Voigt output length must be at least {NTENS_PLANE}, got {len}"
            ),
            Self::BadMatrixLen { len } => {
                write!(
                    f,
                    "3x3 matrix must have 9 elements (column-major), got {len}"
                )
            }
        }
    }
}

impl std::error::Error for VoigtError {}

/// Fortran-style 1-based, column-major element access: `at(a, i, j) == A(i,j)`.
#[inline(always)]
fn at(a: &Mat3, i: usize, j: usize) -> f64 {
    a[(i - 1) + 3 * (j - 1)]
}

/// Resurrection of F77 `SUBROUTINE VMATMUL(A,B,N,C)`
/// (`targets/bioumat/SUBROUTINES.FOR`, line 423).
///
/// Computes the matrix product `A*B` and stores it in Voigt order
/// `C = [11, 22, 33, 12, 13, 23]`. `N` is `c.len()`.
///
/// Behaviour kept from the original:
/// - `C(1..4)` are always written.
/// - `C(5)` and `C(6)` are written only when `N == 6`.
/// - Any other entries of `c` are left untouched (also for `N == 5` or `N > 6`).
/// - Each entry is summed left to right, exactly as written in the source.
///
/// Difference from the original: `N < 4` returns an error instead of writing
/// out of bounds.
pub fn vmatmul(a: &Mat3, b: &Mat3, c: &mut [f64]) -> Result<(), VoigtError> {
    let n = c.len();
    if n < NTENS_PLANE {
        return Err(VoigtError::OutputTooShort { len: n });
    }
    c[0] = at(a, 1, 1) * at(b, 1, 1) + at(a, 1, 2) * at(b, 2, 1) + at(a, 1, 3) * at(b, 3, 1);
    c[1] = at(a, 2, 1) * at(b, 1, 2) + at(a, 2, 2) * at(b, 2, 2) + at(a, 2, 3) * at(b, 3, 2);
    c[2] = at(a, 3, 1) * at(b, 1, 3) + at(a, 3, 2) * at(b, 2, 3) + at(a, 3, 3) * at(b, 3, 3);
    c[3] = at(a, 1, 1) * at(b, 1, 2) + at(a, 1, 2) * at(b, 2, 2) + at(a, 1, 3) * at(b, 3, 2);
    if n == NTENS_SOLID {
        c[4] = at(a, 1, 1) * at(b, 1, 3) + at(a, 1, 2) * at(b, 2, 3) + at(a, 1, 3) * at(b, 3, 3);
        c[5] = at(a, 2, 1) * at(b, 1, 3) + at(a, 2, 2) * at(b, 2, 3) + at(a, 2, 3) * at(b, 3, 3);
    }
    Ok(())
}

/// Slice-based wrapper around [`vmatmul`] used by the wasm entrypoint.
///
/// Returns a zero-initialised vector of length `n` filled as `VMATMUL` would
/// fill it (entries the original does not write stay `0.0`).
pub fn vmatmul_voigt(a: &[f64], b: &[f64], n: usize) -> Result<Vec<f64>, VoigtError> {
    let a: &Mat3 = a
        .try_into()
        .map_err(|_| VoigtError::BadMatrixLen { len: a.len() })?;
    let b: &Mat3 = b
        .try_into()
        .map_err(|_| VoigtError::BadMatrixLen { len: b.len() })?;
    let mut c = vec![0.0; n];
    vmatmul(a, b, &mut c)?;
    Ok(c)
}

/// JavaScript entrypoint for `VMATMUL`.
///
/// `a` and `b` are 9-element `Float64Array`s in column-major order; `n` is the
/// Voigt length (4 or 6). Returns a `Float64Array` of length `n`.
#[wasm_bindgen(js_name = vmatmul)]
pub fn vmatmul_wasm(a: &[f64], b: &[f64], n: usize) -> Result<Vec<f64>, JsError> {
    vmatmul_voigt(a, b, n).map_err(|e| JsError::new(&e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    const I3: Mat3 = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0];

    #[test]
    fn identity_gives_voigt_identity() {
        let mut c = [0.0; NTENS_SOLID];
        vmatmul(&I3, &I3, &mut c).unwrap();
        assert_eq!(c, [1.0, 1.0, 1.0, 0.0, 0.0, 0.0]);
    }

    #[test]
    fn column_major_layout() {
        // A(1,2) = 2 lives at index 3; A * I must return it in C(4) = (A*B)(1,2).
        let mut a = I3;
        a[3] = 2.0;
        let mut c = [0.0; NTENS_PLANE];
        vmatmul(&a, &I3, &mut c).unwrap();
        assert_eq!(c, [1.0, 1.0, 1.0, 2.0]);
    }

    #[test]
    fn entries_beyond_four_untouched_unless_n_is_six() {
        let mut c = [7.0; 5];
        vmatmul(&I3, &I3, &mut c).unwrap();
        assert_eq!(c, [1.0, 1.0, 1.0, 0.0, 7.0]);
    }

    #[test]
    fn short_output_is_an_error() {
        let mut c = [0.0; 3];
        assert_eq!(
            vmatmul(&I3, &I3, &mut c),
            Err(VoigtError::OutputTooShort { len: 3 })
        );
    }

    #[test]
    fn voigt_wrapper_validates_lengths() {
        assert_eq!(
            vmatmul_voigt(&[1.0; 8], &I3, 6),
            Err(VoigtError::BadMatrixLen { len: 8 })
        );
        assert_eq!(
            vmatmul_voigt(&I3, &I3, 6).unwrap(),
            vec![1.0, 1.0, 1.0, 0.0, 0.0, 0.0]
        );
    }
}
