import { useMemo, useState, type MouseEvent } from "react";
import { fmt } from "./ui";

export interface Series {
  name: string;
  color: string;
  ys: number[];
  dashed?: boolean;
}

function niceTicks(lo: number, hi: number, count = 5): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [];
  if (lo === hi) {
    lo -= 1;
    hi += 1;
  }
  const raw = (hi - lo) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => raw <= s) ?? 10 * mag;
  const out: number[] = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi + step * 1e-9; t += step) out.push(+t.toPrecision(12));
  return out;
}

export function LineChart({
  xs,
  series,
  xLabel,
  yLabel,
  marker,
  height = 260,
  width = 640,
}: {
  xs: number[];
  series: Series[];
  xLabel: string;
  yLabel: string;
  marker?: number;
  height?: number;
  width?: number;
}) {
  const W = width;
  const H = height;
  const pad = { l: 64, r: 16, t: 14, b: 40 };
  const [hover, setHover] = useState<number | null>(null);

  const { x0, x1, y0, y1 } = useMemo(() => {
    const finite = series.flatMap((s) => s.ys.filter(Number.isFinite));
    let lo = Math.min(...finite, 0);
    let hi = Math.max(...finite, 0);
    const span = hi - lo || 1;
    lo -= span * 0.06;
    hi += span * 0.06;
    return { x0: xs[0], x1: xs[xs.length - 1], y0: lo, y1: hi };
  }, [xs, series]);

  const sx = (x: number) => pad.l + ((x - x0) / (x1 - x0)) * (W - pad.l - pad.r);
  const sy = (y: number) => pad.t + (1 - (y - y0) / (y1 - y0)) * (H - pad.t - pad.b);
  const path = (ys: number[]) =>
    ys
      .map((y, i) => (Number.isFinite(y) ? `${i === 0 || !Number.isFinite(ys[i - 1]) ? "M" : "L"}${sx(xs[i]).toFixed(1)},${sy(y).toFixed(1)}` : ""))
      .join("");

  const xt = niceTicks(x0, x1, 6);
  const yt = niceTicks(y0, y1, 5);

  const onMove = (e: MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    const x = x0 + ((px - pad.l) / (W - pad.l - pad.r)) * (x1 - x0);
    let best = 0;
    for (let i = 1; i < xs.length; i++) if (Math.abs(xs[i] - x) < Math.abs(xs[best] - x)) best = i;
    setHover(px >= pad.l && px <= W - pad.r ? best : null);
  };

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full select-none"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        role="img"
        aria-label={`${yLabel} versus ${xLabel}`}
      >
        <rect x={pad.l} y={pad.t} width={W - pad.l - pad.r} height={H - pad.t - pad.b} fill="rgb(255 255 255 / 0.015)" rx={6} />
        {yt.map((t) => (
          <g key={`y${t}`}>
            <line x1={pad.l} x2={W - pad.r} y1={sy(t)} y2={sy(t)} stroke={t === 0 ? "#414a63" : "#1f2433"} strokeWidth={t === 0 ? 1.2 : 1} />
            <text x={pad.l - 8} y={sy(t) + 4} textAnchor="end" className="fill-bone-500 font-mono" fontSize={11}>
              {fmt(t, 3)}
            </text>
          </g>
        ))}
        {xt.map((t) => (
          <g key={`x${t}`}>
            <line x1={sx(t)} x2={sx(t)} y1={pad.t} y2={H - pad.b} stroke="#1f2433" />
            <text x={sx(t)} y={H - pad.b + 16} textAnchor="middle" className="fill-bone-500 font-mono" fontSize={11}>
              {fmt(t, 3)}
            </text>
          </g>
        ))}
        <text x={(pad.l + W - pad.r) / 2} y={H - 6} textAnchor="middle" className="fill-bone-300" fontSize={12}>
          {xLabel}
        </text>
        <text transform={`translate(14 ${(pad.t + H - pad.b) / 2}) rotate(-90)`} textAnchor="middle" className="fill-bone-300" fontSize={12}>
          {yLabel}
        </text>
        {series.map((s) => (
          <path key={s.name} d={path(s.ys)} fill="none" stroke={s.color} strokeWidth={2} strokeDasharray={s.dashed ? "5 4" : undefined} strokeLinejoin="round" />
        ))}
        {marker !== undefined && marker >= x0 && marker <= x1 && (
          <line x1={sx(marker)} x2={sx(marker)} y1={pad.t} y2={H - pad.b} stroke="#ffb347" strokeDasharray="3 3" />
        )}
        {hover !== null && (
          <g>
            <line x1={sx(xs[hover])} x2={sx(xs[hover])} y1={pad.t} y2={H - pad.b} stroke="#8a867d" strokeWidth={0.8} />
            {series.map((s) =>
              Number.isFinite(s.ys[hover]) ? <circle key={s.name} cx={sx(xs[hover])} cy={sy(s.ys[hover])} r={3.5} fill={s.color} /> : null,
            )}
          </g>
        )}
      </svg>
      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        {series.map((s) => (
          <span key={s.name} className="inline-flex items-center gap-1.5 text-bone-300">
            <span className="inline-block h-0.5 w-4 rounded" style={{ background: s.color }} />
            {s.name}
            {hover !== null && <span className="font-mono text-bone-50 tabular-nums">{fmt(s.ys[hover], 4)}</span>}
          </span>
        ))}
        {hover !== null && (
          <span className="ml-auto font-mono text-bone-500">
            {xLabel.split(" ")[0]} = {fmt(xs[hover], 4)}
          </span>
        )}
      </div>
    </div>
  );
}
