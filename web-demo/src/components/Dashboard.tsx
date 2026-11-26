import { useEffect, useMemo, useState } from "react";
import { GITHUB_REPO, RUN_LOG, SOURCE_LINES, SPEC } from "../data";
import { HealPanel } from "./HealPanel";
import { PrPanel } from "./PrPanel";
import { SourceViewer } from "./SourceViewer";
import { SpecPanel } from "./SpecPanel";
import { StateGraph } from "./StateGraph";
import { Chip, Panel, Stat, ms } from "./ui";

const log = RUN_LOG;
const total = log.transitions.length;

export function Dashboard() {
  const [unitName, setUnitName] = useState("UMAT");
  const unit = useMemo(() => SPEC.units.find((u) => u.name === unitName) ?? null, [unitName]);
  const [revealed, setRevealed] = useState(total);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    if (!playing) return;
    if (revealed >= total) {
      setPlaying(false);
      return;
    }
    const id = setTimeout(() => setRevealed((r) => r + 1), 750);
    return () => clearTimeout(id);
  }, [playing, revealed]);

  const replay = () => {
    setRevealed(0);
    setPlaying(true);
  };

  const steps = log.steps.slice(0, Math.max(0, revealed - 1) + (revealed === total ? 1 : 0));
  const gate = log.gate_runs.at(-1);
  const wasm = gate?.checks.find((c) => c.check === "wasm_pack")?.metrics as { wasm_bytes?: number } | undefined;
  const bit = log.parity?.bit_identical[0];
  const resurrected = Object.values(log.scope).filter((s) => s.status === "scheduled").length;

  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <Stat label="Units parsed" value={SPEC.summary.units} sub={`${SPEC.source.lines} lines · ${SPEC.source.line_endings}`} />
        <Stat label="Resurrected" value={`${resurrected}/${SPEC.summary.units}`} sub="leaves first" tone="ecto" />
        <Stat label="proptest cases" value={(log.parity?.total_cases ?? 0).toLocaleString()} sub="vs gfortran oracle" tone="ecto" />
        <Stat label="UMAT bit-identical" value={bit ? `${((bit.identical / bit.total) * 100).toFixed(0)}%` : "–"} sub={bit ? `${bit.identical.toLocaleString()}/${bit.total.toLocaleString()} entries` : ""} tone="ecto" />
        <Stat label="GO TOs" value={SPEC.summary.gotos} sub={`${SPEC.summary.backward_gotos} backward → loops`} tone="ember" />
        <Stat label="Gate attempts" value={log.gate_runs.length} sub={`${log.heals.length} self-heal${log.heals.length === 1 ? "" : "s"} (max 5)`} tone={log.heals.length ? "ember" : "ecto"} />
        <Stat label="WASM" value={wasm?.wasm_bytes ? `${(wasm.wasm_bytes / 1024).toFixed(1)} KB` : "–"} sub="wasm-pack --target web" tone="spirit" />
        <Stat label="Outcome" value={log.outcome ?? "–"} sub={`run ${log.run_id} · ${log.mode}`} tone={log.outcome === "success" ? "ecto" : "blood"} />
      </div>

      <Panel
        title="Swarm state graph"
        icon="🕸️"
        right={
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs text-bone-500">
              {revealed}/{total} transitions
            </span>
            <button type="button" onClick={replay} className="rounded-lg border border-ecto-500/50 bg-ecto-900/40 px-3 py-1 text-xs font-medium text-ecto-300 hover:bg-ecto-900/70">
              ▶ Replay run
            </button>
            <button type="button" onClick={() => setPlaying((p) => !p)} disabled={revealed >= total} className="rounded-lg border border-crypt-600 bg-crypt-800 px-3 py-1 text-xs text-bone-300 disabled:opacity-40">
              {playing ? "Pause" : "Resume"}
            </button>
          </div>
        }
      >
        <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
          <StateGraph log={log} revealed={revealed} />
          <ol className="scroll-thin max-h-64 space-y-1.5 overflow-auto pr-1 text-xs">
            {steps.map((s) => (
              <li key={s.seq} className="flex gap-2 rounded-lg border border-crypt-700 bg-crypt-850 px-2.5 py-1.5">
                <span className={`mt-0.5 h-2 w-2 shrink-0 rounded-full ${s.status === "ok" ? (s.state === "SELF_HEAL" ? "bg-ember-400" : "bg-ecto-400") : "bg-blood-400"}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono font-semibold text-bone-50">{s.state}</span>
                    <span className="font-mono text-bone-500">
                      {new Date(s.started_at).toISOString().slice(11, 23)} · {ms(s.duration_ms)}
                    </span>
                  </div>
                  <p className="text-bone-300">{s.summary}</p>
                </div>
              </li>
            ))}
            {steps.length === 0 && <li className="text-bone-500">Replaying…</li>}
          </ol>
        </div>
        {gate && (
          <div className="mt-3 flex flex-wrap gap-2">
            {gate.checks.map((c) => (
              <Chip key={c.check} tone={c.ok ? "ecto" : "blood"}>
                {c.ok ? "✓" : "✗"} {c.check} · {ms(c.duration_ms)}
              </Chip>
            ))}
            {Object.entries(log.toolchain).map(([k, v]) => (
              <Chip key={k}>{v ?? `${k}: missing`}</Chip>
            ))}
          </div>
        )}
      </Panel>

      <div className="grid gap-5 xl:grid-cols-[1.25fr_1fr]">
        <Panel
          title="The Graveyard · SUBROUTINES.FOR"
          icon="🪦"
          className="h-[640px]"
          right={<span className="font-mono text-[11px] text-bone-500">sha256 {SPEC.source.sha256.slice(0, 12)}… · unmodified</span>}
        >
          <div className="flex h-full min-h-0 flex-col gap-3">
            <div className="flex flex-wrap gap-1.5">
              {SPEC.units.map((u) => {
                const st = log.scope[u.name]?.status;
                const active = u.name === unitName;
                return (
                  <button
                    type="button"
                    key={u.name}
                    onClick={() => setUnitName(u.name)}
                    className={`rounded-lg border px-2.5 py-1 font-mono text-xs transition ${active ? "border-ecto-400 bg-ecto-900/60 text-ecto-300" : "border-crypt-600 bg-crypt-800 text-bone-300 hover:border-crypt-500"}`}
                  >
                    {st === "scheduled" ? "🧟 " : st === "out_of_scope" ? "⚰️ " : "💀 "}
                    {u.name}
                  </button>
                );
              })}
            </div>
            <div className="min-h-0 flex-1">
              <SourceViewer lines={SOURCE_LINES} unit={unit} />
            </div>
          </div>
        </Panel>
        <Panel title="Generated Kiro spec" icon="📜" className="h-[640px]" right={<span className="font-mono text-[11px] text-bone-500">{SPEC.schema}</span>}>
          {unit && <SpecPanel unit={unit} log={log} />}
        </Panel>
      </div>

      <div className="grid gap-5 xl:grid-cols-[2.2fr_1fr]">
        <Panel title="Counterexample caught & auto-repaired" icon="🧪">
          <HealPanel log={log} />
        </Panel>
        <Panel title="GitHub PR" icon="🔗">
          <PrPanel pr={log.pr} repo={GITHUB_REPO} />
        </Panel>
      </div>
    </div>
  );
}
