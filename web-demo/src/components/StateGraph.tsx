import type { RunLog } from "../types";

const POS: Record<string, [number, number]> = {
  PARSE: [70, 64],
  SPEC: [192, 64],
  TRANSMUTE: [324, 64],
  ORACLE_GATE: [472, 64],
  PR: [616, 64],
  DONE: [726, 64],
  SELF_HEAL: [472, 182],
  BLOCKED: [660, 182],
};
const LABEL: Record<string, string> = {
  PARSE: "Parse",
  SPEC: "Spec",
  TRANSMUTE: "Transmute",
  ORACLE_GATE: "Oracle Gate",
  SELF_HEAL: "Self-Heal",
  PR: "PR",
  DONE: "Done",
  BLOCKED: "Blocked",
};
const SUB: Record<string, string> = {
  PARSE: "f77_analyzer",
  SPEC: "spec.json/.md",
  TRANSMUTE: "stage Rust ports",
  ORACLE_GATE: "4-check gate",
  SELF_HEAL: "≤ 5 attempts",
  PR: "draft PR",
  DONE: "",
  BLOCKED: "report blocker",
};

/**
 * The orchestrator state machine, drawn from run_log.graph, with the first
 * `revealed` transitions of the recorded run highlighted.
 */
export function StateGraph({ log, revealed }: { log: RunLog; revealed: number }) {
  const shown = log.transitions.slice(0, revealed);
  const current = shown.length ? shown[shown.length - 1].to : null;
  const visits: Record<string, number> = {};
  const traversed = new Map<string, number>();
  for (const t of shown) {
    visits[t.to] = (visits[t.to] ?? 0) + 1;
    if (t.from) traversed.set(`${t.from}>${t.to}`, (traversed.get(`${t.from}>${t.to}`) ?? 0) + 1);
  }
  const failedSteps = new Set(
    log.steps.slice(0, Math.max(0, revealed - 1)).filter((s) => s.status === "failed").map((s) => s.seq),
  );
  const failedStates = new Set(log.steps.filter((s) => failedSteps.has(s.seq)).map((s) => s.state));

  const W = 112;
  const H = 46;

  const edgePath = (a: string, b: string): string => {
    const [x1, y1] = POS[a];
    const [x2, y2] = POS[b];
    if (a === "ORACLE_GATE" && b === "SELF_HEAL") return `M${x1 - 26},${y1 + H / 2} C${x1 - 40},${y1 + 70} ${x2 - 40},${y2 - 70} ${x2 - 26},${y2 - H / 2}`;
    if (a === "SELF_HEAL" && b === "ORACLE_GATE") return `M${x1 + 26},${y1 - H / 2} C${x1 + 40},${y1 - 70} ${x2 + 40},${y2 + 70} ${x2 + 26},${y2 + H / 2}`;
    if (y1 === y2) return `M${x1 + W / 2},${y1} L${x2 - W / 2 + (b === "DONE" ? 40 : 0)},${y2}`;
    return `M${x1},${y1 + H / 2} Q${(x1 + x2) / 2},${(y1 + y2) / 2 + 30} ${x2 - W / 2 + 10},${y2}`;
  };

  return (
    <svg viewBox="0 0 800 230" className="h-auto w-full" role="img" aria-label="Orchestrator state graph">
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="#414a63" />
        </marker>
        <marker id="arrow-hot" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="#6ff09a" />
        </marker>
        <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="4" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      {log.graph.edges
        .filter(([a, b]) => POS[a] && POS[b])
        .map(([a, b]) => {
          const n = traversed.get(`${a}>${b}`) ?? 0;
          const toBlocked = b === "BLOCKED";
          return (
            <g key={`${a}>${b}`}>
              <path
                d={edgePath(a, b)}
                fill="none"
                stroke={n ? (b === "SELF_HEAL" ? "#ffb347" : "#6ff09a") : toBlocked ? "#2c3347" : "#414a63"}
                strokeWidth={n ? 2.2 : 1.2}
                strokeDasharray={toBlocked && !n ? "3 4" : undefined}
                markerEnd={`url(#${n ? "arrow-hot" : "arrow"})`}
                opacity={toBlocked && !n ? 0.5 : 1}
              />
            </g>
          );
        })}
      {Object.entries(POS).map(([s, [x, y]]) => {
        const v = visits[s] ?? 0;
        const isCur = s === current;
        const failed = failedStates.has(s);
        const w = s === "DONE" ? 60 : W;
        const stroke = isCur
          ? s === "BLOCKED"
            ? "#ff5d6c"
            : "#6ff09a"
          : v
            ? s === "SELF_HEAL"
              ? "#ffb347"
              : "#34d978"
            : "#2c3347";
        return (
          <g key={s} transform={`translate(${x - w / 2} ${y - H / 2})`} filter={isCur ? "url(#glow)" : undefined}>
            <rect width={w} height={H} rx={12} fill={v ? "#10131c" : "#0b0d14"} stroke={stroke} strokeWidth={isCur ? 2.4 : 1.4} />
            <text x={w / 2} y={s === "DONE" ? 28 : 20} textAnchor="middle" fontSize={13} fontWeight={600} fill={v ? "#ece8df" : "#8a867d"}>
              {LABEL[s]}
            </text>
            {s !== "DONE" && (
              <text x={w / 2} y={35} textAnchor="middle" fontSize={9.5} fill="#8a867d">
                {SUB[s]}
              </text>
            )}
            {v > 1 && (
              <g transform={`translate(${w - 8} -6)`}>
                <circle r={10} fill="#3a2709" stroke="#ffb347" />
                <text y={4} textAnchor="middle" fontSize={10} fontWeight={700} fill="#ffd08a">
                  ×{v}
                </text>
              </g>
            )}
            {failed && (
              <g transform="translate(8 -6)">
                <circle r={9} fill="#3b1016" stroke="#ff5d6c" />
                <text y={4} textAnchor="middle" fontSize={11} fontWeight={700} fill="#ff9aa4">
                  !
                </text>
              </g>
            )}
          </g>
        );
      })}
    </svg>
  );
}
