import { fmt } from "./ui";

/** NTENS x NTENS column-major matrix as a diverging heatmap. */
export function Heatmap({ data, n, labels }: { data: Float64Array; n: number; labels: string[] }) {
  let max = 0;
  for (const v of data) if (Number.isFinite(v)) max = Math.max(max, Math.abs(v));
  const cell = (r: number, c: number) => data[r + n * c];
  return (
    <div className="overflow-x-auto scroll-thin">
      <table className="border-separate border-spacing-1 font-mono text-[11px]">
        <thead>
          <tr>
            <th />
            {labels.slice(0, n).map((l) => (
              <th key={l} className="px-1 font-medium text-bone-500">
                ε{l}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: n }, (_, r) => (
            <tr key={r}>
              <th className="pr-1 text-right font-medium text-bone-500">σ{labels[r]}</th>
              {Array.from({ length: n }, (_, c) => {
                const v = cell(r, c);
                const t = max > 0 ? Math.min(1, Math.abs(v) / max) : 0;
                const bg =
                  v >= 0 ? `rgb(52 217 120 / ${0.08 + 0.62 * t})` : `rgb(255 93 108 / ${0.08 + 0.62 * t})`;
                return (
                  <td
                    key={c}
                    title={`DDSDDE(${r + 1},${c + 1}) = ${v}`}
                    className="min-w-16 rounded-md px-2 py-1.5 text-right tabular-nums text-bone-50"
                    style={{ background: bg }}
                  >
                    {fmt(v, 3)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
