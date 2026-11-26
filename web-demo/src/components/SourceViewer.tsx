import { useEffect, useMemo, useRef } from "react";
import type { SpecUnit } from "../types";

const LINE_H = 20;
const RULER = Array.from({ length: 80 }, (_, i) => ((i + 1) % 10 === 0 ? String(((i + 1) / 10) % 10) : "·")).join("");

/**
 * The untouched fixed-form source with the column zones shaded:
 * 1-5 label, 6 continuation, 7-72 statement, 73-80 ignored.
 */
export function SourceViewer({ lines, unit }: { lines: string[]; unit: SpecUnit | null }) {
  const ref = useRef<HTMLDivElement>(null);
  const gotoLines = useMemo(() => new Set(unit?.gotos.map((g) => g.line) ?? []), [unit]);
  const labelLines = useMemo(() => new Set(Object.values(unit?.labels ?? {})), [unit]);
  const hazardLines = useMemo(
    () => new Map((unit?.hazards ?? []).filter((h) => h.severity !== "info").map((h) => [h.line, h])),
    [unit],
  );

  useEffect(() => {
    if (unit && ref.current) ref.current.scrollTo({ top: Math.max(0, (unit.line_start - 3) * LINE_H), behavior: "smooth" });
  }, [unit]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-2 flex flex-wrap gap-3 text-[11px] text-bone-500">
        <Legend cls="bg-ember-400/25" label="cols 1-5 label" />
        <Legend cls="bg-spirit-400/30" label="col 6 continuation" />
        <Legend cls="bg-crypt-700" label="cols 7-72 statement" />
        <Legend cls="bg-blood-400/25" label="cols 73-80 ignored" />
      </div>
      <div ref={ref} className="scroll-thin relative min-h-0 flex-1 overflow-auto rounded-xl border border-crypt-700 bg-crypt-950/80 font-mono text-[12.5px]">
        <div className="sticky top-0 z-10 flex border-b border-crypt-700 bg-crypt-900/95 text-bone-500 backdrop-blur" style={{ lineHeight: `${LINE_H}px` }}>
          <span className="w-12 shrink-0 pr-3 text-right">col</span>
          <span className="whitespace-pre">
            <span className="bg-ember-400/15">{RULER.slice(0, 5)}</span>
            <span className="bg-spirit-400/20">{RULER.slice(5, 6)}</span>
            <span>{RULER.slice(6, 72)}</span>
            <span className="bg-blood-400/15">{RULER.slice(72)}</span>
          </span>
        </div>
        {lines.map((line, i) => {
          const n = i + 1;
          const inUnit = unit && n >= unit.line_start && n <= unit.line_end;
          const comment = /^[Cc*!]/.test(line) || /^\s*!/.test(line);
          const hz = hazardLines.get(n);
          const rowBg = gotoLines.has(n)
            ? "bg-ember-400/15"
            : hz
              ? hz.severity === "error"
                ? "bg-blood-400/15"
                : "bg-spirit-400/10"
              : inUnit
                ? "bg-ecto-500/[0.06]"
                : "";
          return (
            <div key={n} className={`flex ${rowBg} ${labelLines.has(n) ? "shadow-[inset_3px_0_0_#ffb347]" : inUnit ? "shadow-[inset_3px_0_0_#34d978]" : ""}`} style={{ lineHeight: `${LINE_H}px` }} title={hz ? `${hz.code}: ${hz.message}` : undefined}>
              <span className={`w-12 shrink-0 pr-3 text-right select-none ${inUnit ? "text-ecto-400/80" : "text-crypt-500"}`}>{n}</span>
              {comment ? (
                <span className="whitespace-pre text-bone-500/70 italic">{line || " "}</span>
              ) : (
                <span className="whitespace-pre">
                  <span className="bg-ember-400/10 text-ember-300">{line.slice(0, 5).padEnd(5)}</span>
                  <span className="bg-spirit-400/15 text-spirit-300">{line.slice(5, 6).padEnd(1)}</span>
                  <Code text={line.slice(6, 72)} />
                  {line.length > 72 && <span className="bg-blood-400/10 text-blood-300/70">{line.slice(72)}</span>}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Legend({ cls, label }: { cls: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-block h-3 w-3 rounded-sm ${cls}`} />
      {label}
    </span>
  );
}

const KW = /\b(SUBROUTINE|FUNCTION|END\s*IF|ENDIF|ENDDO|END|IF|THEN|ELSE\s*IF|ELSEIF|ELSE|DO|CONTINUE|RETURN|CALL|GO\s*TO|PARAMETER|DIMENSION|DOUBLE\s+PRECISION|INTEGER|CHARACTER\*\d+|INCLUDE|COMMON)\b/gi;

function Code({ text }: { text: string }) {
  const bang = text.indexOf("!");
  const code = bang >= 0 ? text.slice(0, bang) : text;
  const tail = bang >= 0 ? text.slice(bang) : "";
  const parts: { t: string; kw: boolean }[] = [];
  let last = 0;
  for (const m of code.matchAll(KW)) {
    if (m.index > last) parts.push({ t: code.slice(last, m.index), kw: false });
    parts.push({ t: m[0], kw: true });
    last = m.index + m[0].length;
  }
  parts.push({ t: code.slice(last), kw: false });
  return (
    <>
      {parts.map((p, i) => (
        <span key={i} className={p.kw ? "font-semibold text-frost-400" : "text-bone-100"}>
          {p.t}
        </span>
      ))}
      {tail && <span className="text-bone-500/70 italic">{tail}</span>}
    </>
  );
}
