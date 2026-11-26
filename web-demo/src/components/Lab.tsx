import { useEffect, useMemo, useState } from "react";
import { IDENTITY, VOIGT, dfgrd, runUmat, statev, type Deformation, type Material, type UmatOut } from "../bioumat";
import { loadWasm, type WasmInfo } from "../wasm";
import { Heatmap } from "./Heatmap";
import { LineChart } from "./LineChart";
import { Chip, Panel, fmt } from "./ui";

const PRESETS: { name: string; d: Deformation }[] = [
  { name: "Reference F = I", d: IDENTITY },
  { name: "Unconfined compression 15%", d: { ...IDENTITY, l2: 0.85, l1: 1 / Math.sqrt(0.85), l3: 1 / Math.sqrt(0.85) } },
  { name: "Confined compression 15%", d: { ...IDENTITY, l2: 0.85 } },
  { name: "Tension 10%", d: { ...IDENTITY, l2: 1.1 } },
  { name: "Simple shear γ = 0.2", d: { ...IDENTITY, g12: 0.2 } },
];

const SLIDERS: { key: keyof Deformation; label: string; min: number; max: number }[] = [
  { key: "l1", label: "F₁₁ stretch", min: 0.6, max: 1.4 },
  { key: "l2", label: "F₂₂ stretch (depth axis)", min: 0.6, max: 1.4 },
  { key: "l3", label: "F₃₃ stretch", min: 0.6, max: 1.4 },
  { key: "g12", label: "F₁₂ shear", min: -0.5, max: 0.5 },
  { key: "g13", label: "F₁₃ shear", min: -0.5, max: 0.5 },
  { key: "g23", label: "F₂₃ shear", min: -0.5, max: 0.5 },
];

const SWEEP = Array.from({ length: 101 }, (_, i) => 0.75 + i * 0.005);

export function Lab() {
  const [wasm, setWasm] = useState<WasmInfo | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [def, setDef] = useState<Deformation>(PRESETS[1].d);
  const [mat, setMat] = useState<Material>({ depth: 0.5, healthy: true });
  const [ntens, setNtens] = useState<4 | 6>(6);
  const [bench, setBench] = useState<{ calls: number; ms: number } | null>(null);

  useEffect(() => {
    loadWasm().then(setWasm, (e: unknown) => setLoadErr(String(e)));
  }, []);

  const sv = useMemo(() => statev(mat), [mat]);
  const f = useMemo(() => dfgrd(def), [def]);

  const current = useMemo<{ out: UmatOut | null; err: string | null }>(() => {
    if (!wasm) return { out: null, err: null };
    try {
      return { out: runUmat(wasm.api, f, ntens, sv), err: null };
    } catch (e) {
      return { out: null, err: e instanceof Error ? e.message : String(e) };
    }
  }, [wasm, f, ntens, sv]);

  const sweep = useMemo(() => {
    if (!wasm) return null;
    const t0 = performance.now();
    const cols = { s22: [] as number[], fib: [] as number[], mat: [] as number[], gag: [] as number[], b11: [] as number[], b22: [] as number[], b33: [] as number[], b12: [] as number[] };
    for (const l2 of SWEEP) {
      try {
        const o = runUmat(wasm.api, dfgrd({ ...def, l2 }), ntens, sv);
        cols.s22.push(o.stress[1]);
        cols.fib.push(o.statev[9]);
        cols.mat.push(o.statev[10]);
        cols.gag.push(-o.statev[11]);
        cols.b11.push(o.bvec[0]);
        cols.b22.push(o.bvec[1]);
        cols.b33.push(o.bvec[2]);
        cols.b12.push(o.bvec[3]);
      } catch {
        for (const k of Object.keys(cols) as (keyof typeof cols)[]) cols[k].push(Number.NaN);
      }
    }
    return { cols, ms: performance.now() - t0 };
  }, [wasm, def, ntens, sv]);

  const runBench = () => {
    if (!wasm) return;
    const n = 20000;
    const t0 = performance.now();
    let acc = 0;
    for (let i = 0; i < n; i++) {
      const r = wasm.api.umat(f, ntens, sv);
      acc += r.stress[1];
      r.free();
    }
    const dt = performance.now() - t0;
    if (Number.isNaN(acc)) console.warn("non-finite stress in benchmark");
    setBench({ calls: n, ms: dt });
  };

  const out = current.out;
  const det = out?.det ?? Number.NaN;
  const compacted = Number.isFinite(det) && det <= sv[2] + 0.02;
  const fiberDeg = (Math.atan2(sv[3], sv[4]) * 180) / Math.PI;

  return (
    <div className="flex flex-col gap-5">
      <div className="panel flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
        <span className="text-lg">🧬</span>
        <span className="font-medium text-bone-50">Live WASM BioUMAT Lab</span>
        {wasm ? (
          <>
            <Chip tone="ecto">wasm loaded · {(wasm.bytes / 1024).toFixed(1)} KB · {wasm.loadMs.toFixed(0)} ms</Chip>
            <Chip tone="spirit">exports: umat · vmatmul · determinant · transpose · tenf</Chip>
          </>
        ) : loadErr ? (
          <Chip tone="blood">wasm failed to load: {loadErr}</Chip>
        ) : (
          <Chip tone="ember">loading oracle_harness_bg.wasm…</Chip>
        )}
        <span className="ml-auto text-xs text-bone-500">
          Every number below comes from the Rust port of the F77 <code className="kbd">UMAT</code>, compiled to wasm. The native build matches gfortran bit for bit.
        </span>
      </div>

      <div className="grid gap-5 xl:grid-cols-[360px_1fr]">
        <div className="flex flex-col gap-5">
          <Panel title="Deformation gradient F" icon="🦴">
            <div className="mb-3 flex flex-wrap gap-1.5">
              {PRESETS.map((p) => (
                <button type="button" key={p.name} onClick={() => setDef(p.d)} className="rounded-lg border border-crypt-600 bg-crypt-800 px-2 py-1 text-[11px] text-bone-300 hover:border-ecto-500/60 hover:text-ecto-300">
                  {p.name}
                </button>
              ))}
            </div>
            <div className="space-y-2.5">
              {SLIDERS.map((s) => (
                <label key={s.key} className="block text-xs">
                  <span className="flex justify-between text-bone-300">
                    {s.label}
                    <span className="font-mono text-bone-50 tabular-nums">{def[s.key].toFixed(3)}</span>
                  </span>
                  <input
                    type="range"
                    min={s.min}
                    max={s.max}
                    step={0.005}
                    value={def[s.key]}
                    onChange={(e) => setDef({ ...def, [s.key]: Number(e.target.value) })}
                    className="mt-1 w-full"
                  />
                </label>
              ))}
            </div>
            <div className="mt-4 grid grid-cols-[auto_1fr] items-center gap-3">
              <MatrixView f={f} />
              <div className="space-y-1 font-mono text-xs">
                <div className="text-bone-500">J = det F</div>
                <div className={`text-xl ${compacted ? "text-blood-400" : "text-ecto-400"}`}>{fmt(det, 5)}</div>
                {compacted && <div className="text-[11px] text-blood-300">J ≤ NS0: solid fully compacted; the original returns non-finite stress here.</div>}
              </div>
            </div>
            <div className="mt-4 flex items-center gap-2 text-xs">
              <span className="text-bone-500">NTENS</span>
              {[4, 6].map((n) => (
                <button type="button" key={n} onClick={() => setNtens(n as 4 | 6)} className={`rounded-md border px-2.5 py-1 font-mono ${ntens === n ? "border-ecto-400 bg-ecto-900/60 text-ecto-300" : "border-crypt-600 bg-crypt-800 text-bone-300"}`}>
                  {n} {n === 4 ? "plane/axisym" : "3D"}
                </button>
              ))}
            </div>
          </Panel>

          <Panel title="Cartilage material (STATEV)" icon="🩻">
            <label className="block text-xs">
              <span className="flex justify-between text-bone-300">
                Normalised depth z (0 = surface)
                <span className="font-mono text-bone-50">{mat.depth.toFixed(2)}</span>
              </span>
              <input type="range" min={0} max={1} step={0.01} value={mat.depth} onChange={(e) => setMat({ ...mat, depth: Number(e.target.value) })} className="mt-1 w-full" />
            </label>
            <div className="mt-3 flex gap-2 text-xs">
              {[true, false].map((h) => (
                <button type="button" key={String(h)} onClick={() => setMat({ ...mat, healthy: h })} className={`rounded-md border px-2.5 py-1 ${mat.healthy === h ? "border-ecto-400 bg-ecto-900/60 text-ecto-300" : "border-crypt-600 bg-crypt-800 text-bone-300"}`}>
                  {h ? "Healthy (STATEV(1)=1)" : "Osteoarthritic (=2)"}
                </button>
              ))}
            </div>
            <dl className="mt-3 grid grid-cols-2 gap-2 font-mono text-xs">
              <KV k="RH fibril density" v={fmt(sv[1], 4)} />
              <KV k="NS0 solid fraction" v={fmt(sv[2], 4)} />
              <KV k="fibril angle" v={`${fiberDeg.toFixed(1)}°`} />
              <KV k="ALPHA1 (GAG)" v={fmt(sv[7], 3)} />
            </dl>
            <p className="mt-3 text-[11px] leading-relaxed text-bone-500">
              Built the way SDVINI lays out STATEV. SDVINI itself is not resurrected (it does not compile as written); REAL literals are rounded to f32 as
              gfortran would, and ALPHA1 uses the layer index where the original reads an uninitialised slot.
            </p>
          </Panel>
        </div>

        <div className="flex min-w-0 flex-col gap-5">
          <Panel
            title="Cauchy stress σ = UMAT(F)"
            icon="⚡"
            right={
              sweep && (
                <span className="font-mono text-[11px] text-bone-500">
                  sweep: {SWEEP.length} UMAT calls in {sweep.ms.toFixed(1)} ms ({((sweep.ms / SWEEP.length) * 1000).toFixed(0)} µs/call)
                </span>
              )
            }
          >
            {current.err && <p className="mb-3 rounded-lg border border-blood-400/50 bg-blood-900/40 px-3 py-2 text-sm text-blood-300">UMAT error: {current.err}</p>}
            <div className="grid grid-cols-3 gap-2 md:grid-cols-6">
              {VOIGT.slice(0, ntens).map((c, k) => (
                <div key={c} className="rounded-xl border border-crypt-700 bg-crypt-850 px-3 py-2">
                  <div className="font-mono text-[11px] text-bone-500">σ{c}</div>
                  <div className={`font-mono text-lg tabular-nums ${(out?.stress[k] ?? 0) < 0 ? "text-frost-400" : "text-ember-300"}`}>{out ? fmt(out.stress[k], 4) : "…"}</div>
                </div>
              ))}
            </div>
            <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
              <KV k="fibrillar σ22 · STATEV(10)" v={out ? fmt(out.statev[9], 4) : "…"} />
              <KV k="non-fibrillar σ22 · STATEV(11)" v={out ? fmt(out.statev[10], 4) : "…"} />
              <KV k="GAG pressure · STATEV(12)" v={out ? fmt(out.statev[11], 4) : "…"} />
            </div>
            {sweep && (
              <div className="mt-4">
                <LineChart
                  xs={SWEEP}
                  width={1040}
                  height={320}
                  xLabel="λ₂ = F₂₂ (other components fixed)"
                  yLabel="σ₂₂ (MPa)"
                  marker={def.l2}
                  series={[
                    { name: "σ22 total", color: "#6ff09a", ys: sweep.cols.s22 },
                    { name: "fibrillar", color: "#ffb347", ys: sweep.cols.fib, dashed: true },
                    { name: "non-fibrillar", color: "#b18cff", ys: sweep.cols.mat, dashed: true },
                    { name: "−GAG pressure", color: "#6cc7ff", ys: sweep.cols.gag, dashed: true },
                  ]}
                />
              </div>
            )}
          </Panel>

          <div className="grid gap-5 2xl:grid-cols-2">
            <Panel title="Left Cauchy-Green b = F Fᵀ (VMATMUL)" icon="🧮">
              {out && (
                <div className="mb-3 grid grid-cols-6 gap-1.5 font-mono text-xs">
                  {VOIGT.map((c, k) => (
                    <div key={c} className="rounded-md border border-crypt-700 bg-crypt-850 px-2 py-1">
                      <div className="text-[10px] text-bone-500">b{c}</div>
                      <div className="text-bone-50 tabular-nums">{fmt(out.bvec[k], 4)}</div>
                    </div>
                  ))}
                </div>
              )}
              {sweep && (
                <LineChart
                  xs={SWEEP}
                  height={220}
                  xLabel="λ₂ = F₂₂"
                  yLabel="b components"
                  marker={def.l2}
                  series={[
                    { name: "b11", color: "#ffb347", ys: sweep.cols.b11 },
                    { name: "b22", color: "#6ff09a", ys: sweep.cols.b22 },
                    { name: "b33", color: "#b18cff", ys: sweep.cols.b33 },
                    { name: "b12", color: "#6cc7ff", ys: sweep.cols.b12, dashed: true },
                  ]}
                />
              )}
            </Panel>
            <Panel
              title="Jacobian DDSDDE (perturbation, ex-GO TO 80/90)"
              icon="🧊"
              right={
                <button type="button" onClick={runBench} disabled={!wasm} className="rounded-lg border border-ecto-500/50 bg-ecto-900/40 px-2.5 py-1 text-[11px] font-medium text-ecto-300 hover:bg-ecto-900/70 disabled:opacity-40">
                  Benchmark 20k calls
                </button>
              }
            >
              {out && <Heatmap data={out.ddsdde} n={ntens} labels={VOIGT} />}
              {bench && (
                <p className="mt-3 font-mono text-xs text-bone-300">
                  {bench.calls.toLocaleString()} UMAT calls ({ntens + 1} stress passes each) in {bench.ms.toFixed(0)} ms →{" "}
                  <span className="text-ecto-400">{((bench.ms / bench.calls) * 1000).toFixed(2)} µs/call</span>, {Math.round(bench.calls / (bench.ms / 1000)).toLocaleString()} calls/s
                </p>
              )}
            </Panel>
          </div>
        </div>
      </div>
    </div>
  );
}

function MatrixView({ f }: { f: Float64Array }) {
  return (
    <div className="relative grid grid-cols-3 gap-x-3 gap-y-1 rounded-md border-x-2 border-bone-500/60 px-2.5 py-1 font-mono text-xs tabular-nums">
      {[1, 2, 3].flatMap((i) =>
        [1, 2, 3].map((j) => {
          const v = f[i - 1 + 3 * (j - 1)];
          return (
            <span key={`${i}${j}`} className={`text-right ${v === 0 ? "text-crypt-500" : i === j ? "text-ecto-300" : "text-ember-300"}`}>
              {v.toFixed(3)}
            </span>
          );
        }),
      )}
    </div>
  );
}

function KV({ k, v }: { k: string; v: string }) {
  return (
    <div className="rounded-lg border border-crypt-700 bg-crypt-850 px-2.5 py-1.5">
      <dt className="text-[10px] text-bone-500">{k}</dt>
      <dd className="font-mono text-bone-50 tabular-nums">{v}</dd>
    </div>
  );
}
