import type { ReactNode } from "react";
import type { RunLog } from "../types";
import { Chip, fmt } from "./ui";

/** The planted fault, the shrunk counterexample proptest found, and the repair. */
export function HealPanel({ log }: { log: RunLog }) {
  const bug = log.planted_bug;
  const cx = log.counterexamples[0];
  const heal = log.heals[0];
  if (!cx) {
    return (
      <p className="text-sm text-bone-300">
        This run passed the oracle gate on the first attempt, so there was nothing to heal. Run{" "}
        <code className="kbd">python3 orchestrator/graph.py --demo-bug</code> to record a run where proptest catches a planted bug.
      </p>
    );
  }
  const ev = (heal?.evidence ?? {}) as { rust_read_index0?: number; candidates_index0?: number[] };
  const inputName = Object.keys(cx.inputs)[0];
  const input = cx.inputs[inputName] ?? [];
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Step n={1} title="Planted in TRANSMUTE" tone="blood">
        {bug ? (
          <>
            <p className="text-xs text-bone-300">{bug.description}</p>
            <Diff file={`${bug.file}:${bug.line}`} minus={bug.before} plus={bug.after} />
          </>
        ) : (
          <p className="text-xs text-bone-300">Fault introduced during translation.</p>
        )}
      </Step>

      <Step n={2} title="Caught by proptest vs gfortran" tone="ember">
        <div className="flex flex-wrap gap-1.5">
          <Chip tone="ember">{cx.property}</Chip>
          <Chip>{cx.evaluations?.toLocaleString()} evaluations incl. shrinking</Chip>
        </div>
        <p className="mt-2 text-xs text-bone-300">
          Shrunk counterexample for <span className="font-mono text-bone-50">{cx.routine}</span>, output{" "}
          <span className="font-mono text-ember-300">{cx.entry}</span>:
        </p>
        <div className="mt-2 flex flex-wrap gap-1 font-mono text-xs">
          {input.map((v, i) => {
            const read = i === ev.rust_read_index0;
            const want = heal?.applied && heal.after?.includes(`[${i}]`);
            return (
              <div
                key={i}
                className={`rounded-md border px-2 py-1 text-center ${read ? "border-blood-400 bg-blood-900/50" : want ? "border-ecto-500 bg-ecto-900/50" : "border-crypt-600 bg-crypt-800"}`}
              >
                <div className="text-[10px] text-bone-500">
                  {inputName}({i + 1}) · [{i}]
                </div>
                <div className="text-bone-50">{fmt(v, 5)}</div>
              </div>
            );
          })}
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-2 font-mono text-xs">
          <div className="rounded-md border border-blood-400/50 bg-blood-900/30 px-2 py-1.5">
            <dt className="text-[10px] text-blood-300">Rust</dt>
            <dd className="text-bone-50">{fmt(cx.rust, 6)}</dd>
          </div>
          <div className="rounded-md border border-ecto-500/50 bg-ecto-900/30 px-2 py-1.5">
            <dt className="text-[10px] text-ecto-300">gfortran oracle</dt>
            <dd className="text-bone-50">{fmt(cx.oracle, 6)}</dd>
          </div>
        </dl>
      </Step>

      <Step n={3} title={`Self-healed (attempt ${heal?.attempt ?? "-"}/${heal?.max_attempts ?? 5})`} tone="ecto">
        {heal ? (
          <>
            <p className="text-xs text-bone-300">{heal.rationale}</p>
            {heal.before && heal.after && <Diff file={`${heal.file}:${heal.line}`} minus={heal.before} plus={heal.after} />}
            <div className="mt-2 flex flex-wrap gap-1.5">
              <Chip tone="spirit">strategy: {heal.strategy}</Chip>
              {heal.matches_reference_translation && <Chip tone="ecto">identical to reference translation</Chip>}
              {log.gate_runs.at(-1)?.ok && <Chip tone="ecto">gate re-run: 4/4 ✓</Chip>}
            </div>
          </>
        ) : (
          <p className="text-xs text-bone-300">No heal recorded.</p>
        )}
      </Step>
    </div>
  );
}

function Step({ n, title, tone, children }: { n: number; title: string; tone: "blood" | "ember" | "ecto"; children: ReactNode }) {
  const ring = { blood: "border-blood-400/40 text-blood-300", ember: "border-ember-400/40 text-ember-300", ecto: "border-ecto-500/40 text-ecto-300" }[tone];
  return (
    <div className="rounded-xl border border-crypt-700 bg-crypt-850 p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className={`grid h-6 w-6 place-items-center rounded-full border font-mono text-xs ${ring}`}>{n}</span>
        <h3 className="text-sm font-semibold text-bone-50">{title}</h3>
      </div>
      {children}
    </div>
  );
}

function Diff({ file, minus, plus }: { file: string; minus: string; plus: string }) {
  return (
    <div className="mt-2 overflow-x-auto rounded-lg border border-crypt-700 bg-crypt-950 font-mono text-[11.5px]">
      <div className="border-b border-crypt-700 px-2 py-1 text-[10px] text-bone-500">{file}</div>
      <pre className="bg-blood-900/40 px-2 py-0.5 text-blood-300">- {minus.trim()}</pre>
      <pre className="bg-ecto-900/40 px-2 py-0.5 text-ecto-300">+ {plus.trim()}</pre>
    </div>
  );
}
