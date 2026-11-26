import type { RunLog, SpecUnit } from "../types";
import { Chip } from "./ui";

const SEV_TONE = { error: "blood", warning: "ember", info: "spirit" } as const;

/** The generated Kiro spec for one F77 unit, plus its resurrection status. */
export function SpecPanel({ unit, log }: { unit: SpecUnit; log: RunLog }) {
  const scope = log.scope[unit.name];
  const cases = log.parity?.cases_per_routine[unit.name];
  const usedArgs = unit.args.filter((a) => a.intent !== "unused");
  const unused = unit.args.length - usedArgs.length;
  return (
    <div className="scroll-thin flex h-full min-h-0 flex-col gap-4 overflow-auto pr-1 text-sm">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="font-mono text-lg font-semibold text-bone-50">{unit.name}</h3>
          <Chip>
            lines {unit.line_start}-{unit.line_end}
          </Chip>
          {scope?.status === "scheduled" ? (
            <Chip tone="ecto">resurrected → {scope.rust}()</Chip>
          ) : scope?.status === "out_of_scope" ? (
            <Chip tone="blood">out of scope</Chip>
          ) : (
            <Chip tone="bone">not scheduled</Chip>
          )}
          {cases ? <Chip tone="ecto">{cases.toLocaleString()} proptest cases ✓</Chip> : null}
        </div>
        <code className="mt-2 block font-mono text-xs break-all text-bone-300">{unit.signature}</code>
        {scope?.reason && <p className="mt-2 text-xs text-bone-500">{scope.reason}</p>}
      </div>

      <dl className="grid grid-cols-2 gap-2 text-xs">
        <Fact k="Implicit typing" v={unit.implicit_rules.join(" · ")} />
        <Fact k="Includes" v={unit.includes.join(", ") || "none"} />
        <Fact k="COMMON blocks" v={unit.common_blocks.map((c) => `/${c.name}/`).join(", ") || "none"} />
        <Fact k="Calls" v={unit.calls.filter((c) => c.valid).map((c) => c.name).join(", ") || "leaf"} />
      </dl>

      {usedArgs.length > 0 && (
        <div>
          <h4 className="mb-1.5 text-[11px] font-semibold tracking-[0.14em] text-bone-500 uppercase">
            Arguments {unused > 0 && <span className="normal-case tracking-normal">({unused} unused not shown)</span>}
          </h4>
          <div className="overflow-x-auto rounded-lg border border-crypt-700">
            <table className="w-full text-left font-mono text-xs">
              <thead className="bg-crypt-800 text-bone-500">
                <tr>
                  <th className="px-2 py-1.5 font-medium">name</th>
                  <th className="px-2 py-1.5 font-medium">F77 type</th>
                  <th className="px-2 py-1.5 font-medium">intent</th>
                  <th className="px-2 py-1.5 font-medium">Rust</th>
                </tr>
              </thead>
              <tbody>
                {usedArgs.map((a) => (
                  <tr key={a.name} className="border-t border-crypt-700/70">
                    <td className="px-2 py-1.5 text-bone-50">
                      {a.name}
                      {a.dims && <span className="text-bone-500">({a.dims.join(",")})</span>}
                    </td>
                    <td className="px-2 py-1.5">
                      {a.type}
                      {a.typing === "implicit" && <span className="ml-1 text-spirit-300">implicit</span>}
                    </td>
                    <td className={`px-2 py-1.5 ${a.intent === "in" ? "text-frost-400" : "text-ember-300"}`}>{a.intent}</td>
                    <td className="px-2 py-1.5 text-bone-300">{a.rust_type}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {unit.gotos.length > 0 && (
        <div>
          <h4 className="mb-1.5 text-[11px] font-semibold tracking-[0.14em] text-bone-500 uppercase">GO TO elimination</h4>
          <ul className="space-y-1 font-mono text-xs">
            {unit.gotos.map((g) => (
              <li key={`${g.line}-${g.label}`} className="flex items-center gap-2">
                <Chip tone="ember">GO TO {g.label}</Chip>
                line {g.line} → {g.target_line}
                <span className="text-bone-500">{g.direction} jump</span>
              </li>
            ))}
          </ul>
          {unit.name === "UMAT" && (
            <p className="mt-1.5 text-xs text-bone-500">
              Rust: <code className="text-ecto-300">for (kkk, &(i, j)) in VOIGT_PAIRS[..ntens]</code> runs the perturbed passes (label 80), then one
              unperturbed pass (label 90). DFGRD1 is never mutated.
            </p>
          )}
        </div>
      )}

      {unit.hazards.length > 0 && (
        <div>
          <h4 className="mb-1.5 text-[11px] font-semibold tracking-[0.14em] text-bone-500 uppercase">Hazards found by the analyzer</h4>
          <ul className="space-y-1.5 text-xs">
            {unit.hazards.map((h, i) => (
              <li key={i} className="flex gap-2">
                <Chip tone={SEV_TONE[h.severity]}>{h.code}</Chip>
                <span className="text-bone-300">
                  <span className="font-mono text-bone-500">L{h.line}</span> {h.message}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <h4 className="mb-1.5 text-[11px] font-semibold tracking-[0.14em] text-bone-500 uppercase">Acceptance criteria (EARS)</h4>
        <ol className="list-decimal space-y-1 pl-5 text-xs text-bone-300">
          {unit.acceptance.map((a, i) => (
            <li key={i}>{a}</li>
          ))}
        </ol>
      </div>
    </div>
  );
}

function Fact({ k, v }: { k: string; v: string }) {
  return (
    <div className="rounded-lg border border-crypt-700 bg-crypt-850 px-2.5 py-1.5">
      <dt className="text-[10px] tracking-[0.12em] text-bone-500 uppercase">{k}</dt>
      <dd className="mt-0.5 font-mono text-bone-100">{v}</dd>
    </div>
  );
}
