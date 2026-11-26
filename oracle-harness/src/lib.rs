#![forbid(unsafe_code)]
//! Safe Rust + WebAssembly resurrections of Fortran 77 kernels from BioUMAT
//! (`targets/bioumat/SUBROUTINES.FOR`, MIT, (c) 2019 Seyed Shayan Sajjadinia).
//!
//! Every routine here is checked against the gfortran-compiled original in
//! `tests/differential_pbt.rs`.
//!
//! | F77 routine   | Rust          | JavaScript (wasm)  |
//! |---------------|---------------|--------------------|
//! | `TRANSPOSE`   | [`transpose`] | `transpose`        |
//! | `DETERMINANT` | [`determinant`] | `determinant`    |
//! | `VMATMUL`     | [`vmatmul`]   | `vmatmul`          |
//! | `TENF`        | [`tenf`]      | `tenf`             |
//! | `UMAT`        | [`umat`]      | `umat` -> `UmatResult` |

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
    /// The input vector is shorter than the 4 entries `TENF` always reads.
    /// In the F77 original this is an out-of-bounds read.
    InputTooShort { len: usize },
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
            Self::InputTooShort { len } => write!(
                f,
                "Voigt input length must be at least {NTENS_PLANE}, got {len}"
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

/// Column-major linear offset of the 1-based Fortran element `(i, j)` of a 3x3 array.
#[inline(always)]
const fn ix(i: usize, j: usize) -> usize {
    (i - 1) + 3 * (j - 1)
}

/// Fortran-style 1-based, column-major element access: `at(a, i, j) == A(i,j)`.
#[inline(always)]
fn at(a: &Mat3, i: usize, j: usize) -> f64 {
    a[ix(i, j)]
}

fn mat3_from_slice(a: &[f64]) -> Result<&Mat3, VoigtError> {
    a.try_into()
        .map_err(|_| VoigtError::BadMatrixLen { len: a.len() })
}

/// Resurrection of F77 `SUBROUTINE TRANSPOSE(A,AT)`
/// (`targets/bioumat/SUBROUTINES.FOR`, line 400).
///
/// The original overwrites every element of `AT`, so returning a fresh matrix is
/// equivalent. (The name shadows the Fortran 90 intrinsic; in F77 it is a plain
/// external.)
pub fn transpose(a: &Mat3) -> Mat3 {
    let mut at_ = [0.0; 9];
    for i in 1..=3 {
        for j in 1..=3 {
            at_[ix(j, i)] = a[ix(i, j)]; // AT(j,i) = A(i,j)
        }
    }
    at_
}

/// Resurrection of F77 `SUBROUTINE DETERMINANT(A,DET)`
/// (`targets/bioumat/SUBROUTINES.FOR`, line 413).
///
/// Cofactor expansion summed left to right in source order, so the result is
/// bit-identical to the original compiled without FMA contraction.
pub fn determinant(a: &Mat3) -> f64 {
    at(a, 1, 1) * at(a, 2, 2) * at(a, 3, 3)
        - at(a, 1, 1) * at(a, 2, 3) * at(a, 3, 2)
        - at(a, 2, 1) * at(a, 1, 2) * at(a, 3, 3)
        + at(a, 2, 1) * at(a, 1, 3) * at(a, 3, 2)
        + at(a, 3, 1) * at(a, 1, 2) * at(a, 2, 3)
        - at(a, 3, 1) * at(a, 1, 3) * at(a, 2, 2)
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
    let a = mat3_from_slice(a)?;
    let b = mat3_from_slice(b)?;
    let mut c = vec![0.0; n];
    vmatmul(a, b, &mut c)?;
    Ok(c)
}

/// Resurrection of F77 `SUBROUTINE TENF(V,N,M)`
/// (`targets/bioumat/SUBROUTINES.FOR`, line 439).
///
/// Expands a Voigt vector `V(N)` into the symmetric 3x3 tensor `M`. `N` is `v.len()`.
/// The original writes all nine entries of `M`; the out-of-plane shear entries
/// come from `V(5)`, `V(6)` only when `N == 6` and are zero otherwise.
///
/// Difference from the original: `N < 4` returns an error instead of reading
/// `V(4)` out of bounds.
pub fn tenf(v: &[f64]) -> Result<Mat3, VoigtError> {
    let n = v.len();
    if n < NTENS_PLANE {
        return Err(VoigtError::InputTooShort { len: n });
    }
    let mut m = [0.0; 9];
    m[ix(1, 1)] = v[0]; // M(1,1)=V(1)
    m[ix(2, 1)] = v[3]; // M(2,1)=V(4)
    if n == NTENS_SOLID {
        m[ix(3, 1)] = v[4]; // M(3,1)=V(5)
    } else {
        m[ix(3, 1)] = 0.0; // M(3,1)=0
    }
    m[ix(1, 2)] = v[3]; // M(1,2)=V(4)
    m[ix(2, 2)] = v[1]; // M(2,2)=V(2)
    if n == NTENS_SOLID {
        m[ix(3, 2)] = v[5]; // M(3,2)=V(6)
        m[ix(1, 3)] = v[4]; // M(1,3)=V(5)
        m[ix(2, 3)] = v[5]; // M(2,3)=V(6)
    } else {
        m[ix(3, 2)] = 0.0; // M(3,2)=0
        m[ix(1, 3)] = 0.0; // M(1,3)=0
        m[ix(2, 3)] = 0.0; // M(2,3)=0
    }
    m[ix(3, 3)] = v[2]; // M(3,3)=V(3)
    Ok(m)
}

// ---------------------------------------------------------------------------
// UMAT
// ---------------------------------------------------------------------------

/// UMAT reads `STATEV(1..8)` and writes `STATEV(10..12)`, so `NSTATV >= 12`.
pub const UMAT_MIN_NSTATV: usize = 12;

/// F77 `EP=10D-8`: perturbation size for the numerical Jacobian (i.e. `1e-7`).
pub const UMAT_PERTURBATION: f64 = 10e-8;

/// F77 `INDEX(1:2, K)`: the tensor index pair behind Voigt component `K`.
const VOIGT_PAIRS: [(usize, usize); 6] = [(1, 1), (2, 2), (3, 3), (1, 2), (1, 3), (2, 3)];

/// F77 `FFD=0.57735026919D0` (1/sqrt(3), the 45-degree fibril direction cosine).
const FFD: f64 = 0.57735026919;

/// Errors for UMAT inputs that would make the original read or write out of bounds.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum UmatError {
    /// `NTENS` must be 4 (plane strain / axisymmetric) or 6 (3D). With `NTENS < 4`
    /// `VMATMUL` writes past `BVEC`; with `NTENS == 5` `BVEC(5)` is read uninitialised.
    BadNtens { ntens: usize },
    /// `STATEV` must hold at least [`UMAT_MIN_NSTATV`] entries.
    StatevTooShort { len: usize },
    /// `STRESS` must have `NTENS` entries and `DDSDDE` `NTENS * NTENS`.
    BadStateShape {
        ntens: usize,
        stress: usize,
        ddsdde: usize,
    },
    /// `DFGRD1` did not have exactly 9 elements.
    BadMatrixLen { len: usize },
}

impl fmt::Display for UmatError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::BadNtens { ntens } => write!(
                f,
                "NTENS must be {NTENS_PLANE} (plane/axisymmetric) or {NTENS_SOLID} (3D), got {ntens}"
            ),
            Self::StatevTooShort { len } => write!(
                f,
                "STATEV must have at least {UMAT_MIN_NSTATV} entries, got {len}"
            ),
            Self::BadStateShape {
                ntens,
                stress,
                ddsdde,
            } => write!(
                f,
                "for NTENS={ntens} STRESS needs {ntens} and DDSDDE {} entries, got {stress} and {ddsdde}",
                ntens * ntens
            ),
            Self::BadMatrixLen { len } => {
                write!(f, "DFGRD1 must have 9 elements (column-major), got {len}")
            }
        }
    }
}

impl std::error::Error for UmatError {}

/// Explicit integration-point state for [`umat`].
///
/// These are the Abaqus arrays the F77 `UMAT` reads and updates through its
/// by-reference arguments. Keeping them in one struct passed as `&mut` replaces
/// the hidden aliasing of the original; there is no global or COMMON state.
///
/// `STATEV` layout used by BioUMAT (1-based, as written by `SDVINI`):
///
/// | Index | Meaning |
/// |-------|---------|
/// | 1 | material type (1 = healthy, anything else = osteoarthritic fibril stiffness) |
/// | 2 | `RH`, total fibrillar density |
/// | 3 | `NS0`, initial solid volume fraction |
/// | 4, 5, 6 | primary fibril direction components (`NVEC0(2)`, `NVEC0(1)`, `NVEC0(3)`) |
/// | 8 | `ALPHA1`, depth-dependent GAG constant |
/// | 10 | output: fibrillar `S22` |
/// | 11 | output: non-fibrillar `S22` |
/// | 12 | output: GAG pressure |
#[derive(Debug, Clone, PartialEq)]
pub struct UmatState {
    /// `NTENS`: 4 or 6.
    pub ntens: usize,
    /// `STRESS(NTENS)`: Cauchy stress in Voigt order, written by [`umat`].
    pub stress: Vec<f64>,
    /// `DDSDDE(NTENS,NTENS)`: consistent Jacobian, column-major, written by [`umat`].
    pub ddsdde: Vec<f64>,
    /// `STATEV(NSTATV)`: solution-dependent state variables.
    pub statev: Vec<f64>,
}

impl UmatState {
    /// Creates a state with zeroed `STRESS`/`DDSDDE` after validating the shapes.
    pub fn new(ntens: usize, statev: Vec<f64>) -> Result<Self, UmatError> {
        let state = Self {
            ntens,
            stress: vec![0.0; ntens],
            ddsdde: vec![0.0; ntens * ntens],
            statev,
        };
        state.validate()?;
        Ok(state)
    }

    fn validate(&self) -> Result<(), UmatError> {
        if self.ntens != NTENS_PLANE && self.ntens != NTENS_SOLID {
            return Err(UmatError::BadNtens { ntens: self.ntens });
        }
        if self.statev.len() < UMAT_MIN_NSTATV {
            return Err(UmatError::StatevTooShort {
                len: self.statev.len(),
            });
        }
        if self.stress.len() != self.ntens || self.ddsdde.len() != self.ntens * self.ntens {
            return Err(UmatError::BadStateShape {
                ntens: self.ntens,
                stress: self.stress.len(),
                ddsdde: self.ddsdde.len(),
            });
        }
        Ok(())
    }
}

/// Material constants UMAT derives from `STATEV` in its INITIALIZATION block.
struct Material {
    healthy: bool,
    alpha1: f64,
    rh: f64,
    ns0: f64,
    nvec0: [f64; 27],
}

/// F77 `ALPHA2=3.22D0`, GAG exponent.
const ALPHA2: f64 = 3.22;
/// F77 `C=3.009D0`, fibrillar relative density constant.
const C_FIB: f64 = 3.009;

impl Material {
    fn from_statev(statev: &[f64]) -> Self {
        let (s4, s5, s6) = (statev[3], statev[4], statev[5]);
        #[rustfmt::skip]
        let nvec0 = [
            s5, s4, s6,          // NVEC0(1..3): primary fibril
            -s5, s4, -s6,        // NVEC0(4..6): mirrored primary fibril
            1.0, 0.0, 0.0,       // NVEC0(7..9)
            0.0, 1.0, 0.0,       // NVEC0(10..12)
            0.0, 0.0, 1.0,       // NVEC0(13..15)
            FFD, FFD, FFD,       // NVEC0(16..18)
            -FFD, FFD, FFD,      // NVEC0(19..21)
            FFD, -FFD, FFD,      // NVEC0(22..24)
            FFD, FFD, -FFD,      // NVEC0(25..27)
        ];
        Self {
            healthy: statev[0] == 1.0, // F77: IF (STATEV(1).NE.1) => OA
            alpha1: statev[7],
            rh: statev[1],
            ns0: statev[2],
            nvec0,
        }
    }
}

/// Result of one pass through the F77 "STRESS CALCULATIONS" block.
struct StressPass {
    stress: Vec<f64>,
    det: f64,
    fibril_s22: f64,
    nonfibril_s22: f64,
    gag: f64,
}

/// One pass through the F77 "STRESS CALCULATIONS" block for deformation gradient `f`.
fn stress_pass(f: &Mat3, ntens: usize, mat: &Material) -> StressPass {
    let tranf = transpose(f);
    let mut bvec = vec![0.0; ntens];
    // ntens is 4 or 6 (validated), which is always long enough for VMATMUL.
    vmatmul(f, &tranf, &mut bvec).expect("ntens validated");
    let det = determinant(f);

    // Fibrillar network: 9 fibril families (primary, mirrored primary, 7 secondary).
    let hh = mat.ns0 * (mat.rh * C_FIB) / (2.0 * C_FIB + 7.0);
    let mut e1mp = 4.63;
    let mut e2mp = 3670.0;
    if !mat.healthy {
        e2mp = 3670.0 / 4.0; // F77: E2MP=3670/FOUR (INTEGER 3670 promoted)
    }
    e1mp *= hh;
    e2mp *= hh;
    let mut stress = vec![0.0; ntens];
    for i in 0..=8 {
        if i == 2 {
            // Secondary fibrils have lower density by the factor C.
            e1mp /= C_FIB;
            e2mp /= C_FIB;
        }
        let mut fv1 = [0.0; 3];
        for (m, fv) in fv1.iter_mut().enumerate() {
            for n in 1..=3 {
                // FV1(m)=DFGRD1(m,n)*NVEC0(3*i+n)+FV1(m); IEEE addition commutes.
                *fv += f[ix(m + 1, n)] * mat.nvec0[3 * i + n - 1];
            }
        }
        // F77: FV1(1)**TWO. gfortran folds x**2.0D0 to x*x.
        let landa = (fv1[0] * fv1[0] + fv1[1] * fv1[1] + fv1[2] * fv1[2]).sqrt();
        let eps = landa.ln();
        if eps > 0.0 {
            // Fibrils carry load in tension only.
            let newv1 = fv1.map(|x| x / landa);
            let str_ = (e1mp + e2mp * eps) * eps * landa / det;
            for (k6, s) in stress.iter_mut().enumerate() {
                let (k3, k4) = VOIGT_PAIRS[k6];
                let vv = newv1[k3 - 1] * newv1[k4 - 1];
                *s += str_ * vv;
            }
        }
    }
    let fibril_s22 = stress[1];

    // Non-fibrillar (proteoglycan) neo-Hookean part.
    let gm = 0.723 * mat.ns0 * (1.0 - mat.rh);
    let w5 = gm / det;
    let ln_det = det.ln();
    let w6 = ((ln_det / 6.0)
        * (((3.0 * mat.ns0 / (det - mat.ns0)) * ((det * ln_det / (det - mat.ns0)) - 2.0)) - 4.0)
        + det.powf(2.0 / 3.0))
        * w5;
    let nstr: Vec<f64> = (0..ntens)
        .map(|k6| {
            let deltav = if k6 < 3 { 1.0 } else { 0.0 };
            -deltav * w6 + bvec[k6] * w5
        })
        .collect();

    // GAG osmotic pressure.
    let gag = mat.alpha1 * det.powf(-ALPHA2);
    for (k6, s) in stress.iter_mut().enumerate() {
        *s = if k6 < 3 {
            nstr[k6] - gag + *s
        } else {
            nstr[k6] + *s
        };
    }
    StressPass {
        stress,
        det,
        fibril_s22,
        nonfibril_s22: nstr[1],
        gag,
    }
}

/// F77 label 80: `DFGRD1 = DFGRD + (I(:,i) (x) DFGRD(j,:) + I(:,j) (x) DFGRD(i,:)) * EP/2`.
fn perturb(base: &Mat3, i: usize, j: usize) -> Mat3 {
    let ident = |a: usize, b: usize| if a == b { 1.0 } else { 0.0 };
    let mut f = [0.0; 9];
    for k1 in 1..=3 {
        for k2 in 1..=3 {
            f[ix(k2, k1)] = base[ix(k2, k1)]
                + (ident(k2, i) * base[ix(j, k1)] + ident(k2, j) * base[ix(i, k1)])
                    * UMAT_PERTURBATION
                    / 2.0;
        }
    }
    f
}

/// Resurrection of F77 `SUBROUTINE UMAT(...)`, the BioUMAT multiphasic cartilage
/// model (`targets/bioumat/SUBROUTINES.FOR`, lines 122-392).
///
/// Computes the Cauchy stress (fibrillar network + non-fibrillar neo-Hookean
/// matrix + GAG osmotic pressure) for the deformation gradient `dfgrd1` at the end
/// of the increment, and the Jacobian `DDSDDE` by forward perturbation. Writes
/// `state.stress`, `state.ddsdde`, and `state.statev[9..12]` (`STATEV(10..12)`);
/// all other `STATEV` entries are left unchanged, as in the original.
///
/// # Control flow
///
/// The original computes the Jacobian with a `GO TO` loop: label 80 perturbs
/// `DFGRD1` for Voigt column `KKK`, label 90 resets `STRESS`/`STATEV` and re-runs
/// the stress block, and the tail jumps back while `KKK <= NTENS`, finishing with
/// one unperturbed pass. Here that is a `for` loop over the `NTENS` perturbed
/// passes followed by the base pass. The original mutates `DFGRD1` in place and
/// restores it before returning; this version never mutates it.
///
/// Only the `DDS=1` (perturbation) path is reachable in the original (`DDS` is a
/// hard-coded constant), so the dead exact-Jacobian branch is not ported.
///
/// Inputs that the original handles without memory errors are reproduced
/// faithfully, including non-finite results (e.g. `det(F) <= 0` gives NaN).
pub fn umat(dfgrd1: &Mat3, state: &mut UmatState) -> Result<(), UmatError> {
    state.validate()?;
    let ntens = state.ntens;
    let mat = Material::from_statev(&state.statev);

    // F77 labels 80/90, KKK = 1..NTENS: one perturbed pass per Voigt column.
    let mut ddsdde = vec![0.0; ntens * ntens];
    for (kkk, &(i, j)) in VOIGT_PAIRS[..ntens].iter().enumerate() {
        let pass = stress_pass(&perturb(dfgrd1, i, j), ntens, &mat);
        for (k5, s) in pass.stress.iter().enumerate() {
            ddsdde[k5 + ntens * kkk] = s * pass.det; // DDSDDE(K5,KKK)=STRESS(K5)*DET
        }
    }

    // KKK = NTENS+1: DFGRD1 restored, final unperturbed pass (label 90).
    let base = stress_pass(dfgrd1, ntens, &mat);
    let w2 = 1.0 / UMAT_PERTURBATION;
    let w1 = w2 / base.det;
    for k6 in 0..ntens {
        for k5 in 0..ntens {
            let d = &mut ddsdde[k5 + ntens * k6];
            *d = w1 * *d - w2 * base.stress[k5];
        }
    }

    state.statev[9] = base.fibril_s22; // STATEV(10)
    state.statev[10] = base.nonfibril_s22; // STATEV(11)
    state.statev[11] = base.gag; // STATEV(12)
    state.stress = base.stress;
    state.ddsdde = ddsdde;
    Ok(())
}

/// Slice-based wrapper around [`umat`]: builds a fresh [`UmatState`], runs UMAT, returns it.
pub fn umat_slices(dfgrd1: &[f64], ntens: usize, statev: &[f64]) -> Result<UmatState, UmatError> {
    let f: &Mat3 = dfgrd1
        .try_into()
        .map_err(|_| UmatError::BadMatrixLen { len: dfgrd1.len() })?;
    let mut state = UmatState::new(ntens, statev.to_vec())?;
    umat(f, &mut state)?;
    Ok(state)
}

// ---------------------------------------------------------------------------
// WebAssembly entrypoints
// ---------------------------------------------------------------------------

fn js_err(e: impl fmt::Display) -> JsError {
    JsError::new(&e.to_string())
}

/// JavaScript entrypoint for `VMATMUL`.
///
/// `a` and `b` are 9-element `Float64Array`s in column-major order; `n` is the
/// Voigt length (4 or 6). Returns a `Float64Array` of length `n`.
#[wasm_bindgen(js_name = vmatmul)]
pub fn vmatmul_wasm(a: &[f64], b: &[f64], n: usize) -> Result<Vec<f64>, JsError> {
    vmatmul_voigt(a, b, n).map_err(js_err)
}

/// JavaScript entrypoint for `TRANSPOSE`: 9-element column-major in and out.
#[wasm_bindgen(js_name = transpose)]
pub fn transpose_wasm(a: &[f64]) -> Result<Vec<f64>, JsError> {
    Ok(transpose(mat3_from_slice(a).map_err(js_err)?).to_vec())
}

/// JavaScript entrypoint for `DETERMINANT`: 9-element column-major matrix.
#[wasm_bindgen(js_name = determinant)]
pub fn determinant_wasm(a: &[f64]) -> Result<f64, JsError> {
    Ok(determinant(mat3_from_slice(a).map_err(js_err)?))
}

/// JavaScript entrypoint for `TENF`: Voigt vector (length >= 4) to a 9-element
/// column-major tensor.
#[wasm_bindgen(js_name = tenf)]
pub fn tenf_wasm(v: &[f64]) -> Result<Vec<f64>, JsError> {
    Ok(tenf(v).map_err(js_err)?.to_vec())
}

/// UMAT output returned to JavaScript.
#[wasm_bindgen]
pub struct UmatResult {
    ntens: usize,
    stress: Vec<f64>,
    ddsdde: Vec<f64>,
    statev: Vec<f64>,
}

#[wasm_bindgen]
impl UmatResult {
    /// `NTENS` used for the call.
    #[wasm_bindgen(getter)]
    pub fn ntens(&self) -> usize {
        self.ntens
    }
    /// Cauchy stress, Voigt order `[11, 22, 33, 12, (13, 23)]`.
    #[wasm_bindgen(getter)]
    pub fn stress(&self) -> Vec<f64> {
        self.stress.clone()
    }
    /// Jacobian `DDSDDE`, `NTENS x NTENS`, column-major.
    #[wasm_bindgen(getter)]
    pub fn ddsdde(&self) -> Vec<f64> {
        self.ddsdde.clone()
    }
    /// Updated `STATEV` (entries 10..12 hold the fibrillar S22, non-fibrillar S22
    /// and GAG pressure).
    #[wasm_bindgen(getter)]
    pub fn statev(&self) -> Vec<f64> {
        self.statev.clone()
    }
}

/// JavaScript entrypoint for `UMAT`.
///
/// `dfgrd1` is the 9-element column-major deformation gradient, `ntens` is 4 or 6,
/// and `statev` holds at least 12 state variables (see [`UmatState`]).
#[wasm_bindgen(js_name = umat)]
pub fn umat_wasm(dfgrd1: &[f64], ntens: usize, statev: &[f64]) -> Result<UmatResult, JsError> {
    let s = umat_slices(dfgrd1, ntens, statev).map_err(js_err)?;
    Ok(UmatResult {
        ntens: s.ntens,
        stress: s.stress,
        ddsdde: s.ddsdde,
        statev: s.statev,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    const I3: Mat3 = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0];

    fn healthy_statev() -> Vec<f64> {
        let mut s = vec![0.0; UMAT_MIN_NSTATV];
        s[0] = 1.0; // healthy
        s[1] = 0.59; // RH
        s[2] = 0.1; // NS0
        s[3] = 0.0; // fibril dir components
        s[4] = 1.0;
        s[7] = 0.005; // ALPHA1
        s
    }

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

    #[test]
    fn transpose_and_determinant_basics() {
        let a: Mat3 = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0];
        let t = transpose(&a);
        assert_eq!(at(&t, 1, 2), at(&a, 2, 1));
        assert_eq!(transpose(&t), a);
        assert_eq!(determinant(&I3), 1.0);
        assert_eq!(determinant(&a), -3.0);
    }

    #[test]
    fn tenf_branches() {
        let m6 = tenf(&[1.0, 2.0, 3.0, 4.0, 5.0, 6.0]).unwrap();
        assert_eq!(m6, [1.0, 4.0, 5.0, 4.0, 2.0, 6.0, 5.0, 6.0, 3.0]);
        let m4 = tenf(&[1.0, 2.0, 3.0, 4.0]).unwrap();
        assert_eq!(m4, [1.0, 4.0, 0.0, 4.0, 2.0, 0.0, 0.0, 0.0, 3.0]);
        assert_eq!(tenf(&[1.0; 3]), Err(VoigtError::InputTooShort { len: 3 }));
    }

    #[test]
    fn umat_reference_state_is_gag_prestress() {
        // At F = I the neo-Hookean part vanishes and the GAG pressure
        // ALPHA1 * 1^-ALPHA2 remains on the diagonal. F77 quirk kept: FFD =
        // 0.57735026919 is rounded *up* from 1/sqrt(3), so the four 45-degree
        // fibrils have |F n| = sqrt(3) * FFD > 1 at F = I and carry ~1e-14 tension.
        let s = umat_slices(&I3, NTENS_SOLID, &healthy_statev()).unwrap();
        for k in 0..3 {
            let residual = s.stress[k] + 0.005;
            assert!(residual > 0.0 && residual < 1e-12, "{:?}", s.stress);
        }
        for k in 3..6 {
            assert!(s.stress[k].abs() < 1e-15);
        }
        assert_eq!(s.statev[11], 0.005);
    }

    #[test]
    fn umat_tension_is_tensile_and_jacobian_is_positive() {
        let mut f = I3;
        f[ix(2, 2)] = 1.1; // 10% stretch along the depth axis
        let s = umat_slices(&f, NTENS_PLANE, &healthy_statev()).unwrap();
        assert!(s.stress[1] > 0.0, "{:?}", s.stress);
        assert!(s.ddsdde[1 + 4] > 0.0, "{:?}", s.ddsdde);
        assert_eq!(s.statev[..9], healthy_statev()[..9]);
    }

    #[test]
    fn umat_validates_shapes() {
        assert_eq!(
            UmatState::new(5, healthy_statev()),
            Err(UmatError::BadNtens { ntens: 5 })
        );
        assert_eq!(
            UmatState::new(6, vec![0.0; 11]),
            Err(UmatError::StatevTooShort { len: 11 })
        );
        assert_eq!(
            umat_slices(&[0.0; 4], 6, &healthy_statev()).map(|_| ()),
            Err(UmatError::BadMatrixLen { len: 4 })
        );
    }
}
