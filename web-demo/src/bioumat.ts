// BioUMAT helpers for the lab: building DFGRD1 and STATEV, and running the
// resurrected UMAT through wasm.
import type { Necro } from "./wasm";

/** 3x3 matrix in Fortran column-major order: A(i,j) at (i-1) + 3*(j-1). */
export type Mat3 = Float64Array;

export interface Deformation {
  l1: number; // F11
  l2: number; // F22 (depth axis, the loading direction in BioUMAT's tests)
  l3: number; // F33
  g12: number; // F12
  g13: number; // F13
  g23: number; // F23
}

export const IDENTITY: Deformation = { l1: 1, l2: 1, l3: 1, g12: 0, g13: 0, g23: 0 };

export function dfgrd(d: Deformation): Mat3 {
  const f = new Float64Array(9);
  f[0] = d.l1;
  f[4] = d.l2;
  f[8] = d.l3;
  f[3] = d.g12; // F(1,2)
  f[6] = d.g13; // F(1,3)
  f[7] = d.g23; // F(2,3)
  return f;
}

export interface Material {
  depth: number; // normalised depth z in [0, 1] (0 = articular surface)
  healthy: boolean;
}

/** Depth-dependent GAG constants G(1..10) from SDVINI. */
const G = [0.005, 0.01, 0.025, 0.035, 0.042, 0.048, 0.053, 0.058, 0.06, 0.06];
const f32 = Math.fround;

/**
 * STATEV as SDVINI lays it out for UMAT. SDVINI itself is not resurrected (it
 * does not compile as written, see the generated spec), so this follows its
 * intent: REAL (f32) literals are rounded with Math.fround as gfortran would,
 * and ALPHA1 uses the layer index STATEV(7) where the original reads the
 * uninitialised STATEV(10).
 */
export function statev(m: Material, nstatv = 12): Float64Array {
  const s = new Float64Array(nstatv);
  const d = m.depth;
  s[0] = m.healthy ? 1 : 2;
  s[1] = f32(1.4) * d ** 2 - f32(1.1) * d + f32(0.59); // RH
  if (d > f32(0.3)) {
    s[3] = 1;
    s[4] = 0;
  } else {
    const phi = 5.235987755983 * d;
    s[3] = Math.sin(phi);
    s[4] = Math.cos(phi);
  }
  s[5] = 0;
  s[2] = (m.healthy ? f32(0.1) : f32(0.05)) + f32(0.2) * d; // NS0
  const layer = Math.trunc(d * 9) + 1;
  s[6] = layer;
  s[7] = G[layer - 1]; // ALPHA1
  s[8] = d;
  return s;
}

export interface UmatOut {
  stress: Float64Array;
  ddsdde: Float64Array;
  statev: Float64Array;
  det: number;
  bvec: Float64Array;
}

export function runUmat(api: Necro, f: Mat3, ntens: number, sv: Float64Array): UmatOut {
  const r = api.umat(f, ntens, sv);
  try {
    const ft = api.transpose(f);
    return {
      stress: r.stress,
      ddsdde: r.ddsdde,
      statev: r.statev,
      det: api.determinant(f),
      bvec: api.vmatmul(f, ft, 6),
    };
  } finally {
    r.free();
  }
}

export const VOIGT = ["11", "22", "33", "12", "13", "23"];
