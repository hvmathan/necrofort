import type { ReactNode } from "react";

export function Panel({
  title,
  icon,
  right,
  children,
  className = "",
}: {
  title: string;
  icon?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel flex min-w-0 flex-col ${className}`}>
      <header className="flex items-center justify-between gap-3 border-b border-crypt-700/70 px-4 py-3">
        <h2 className="panel-title">
          {icon && <span className="text-base leading-none">{icon}</span>}
          {title}
        </h2>
        {right}
      </header>
      <div className="min-h-0 flex-1 p-4">{children}</div>
    </section>
  );
}

const TONES = {
  ecto: "border-ecto-500/40 bg-ecto-900/40 text-ecto-300",
  ember: "border-ember-400/40 bg-ember-900/40 text-ember-300",
  blood: "border-blood-400/40 bg-blood-900/40 text-blood-300",
  spirit: "border-spirit-400/40 bg-spirit-900/40 text-spirit-300",
  bone: "border-crypt-600 bg-crypt-800 text-bone-300",
} as const;
export type Tone = keyof typeof TONES;

export function Chip({ tone = "bone", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`chip ${TONES[tone]}`}>{children}</span>;
}

export function Stat({
  label,
  value,
  sub,
  tone = "bone",
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: Tone;
}) {
  const color = {
    ecto: "text-ecto-400",
    ember: "text-ember-400",
    blood: "text-blood-400",
    spirit: "text-spirit-400",
    bone: "text-bone-50",
  }[tone];
  return (
    <div className="panel px-4 py-3">
      <div className="text-[11px] font-medium tracking-[0.14em] text-bone-500 uppercase">{label}</div>
      <div className={`mt-1 font-mono text-2xl font-semibold tabular-nums ${color}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-bone-500">{sub}</div>}
    </div>
  );
}

export function fmt(x: number, digits = 4): string {
  if (!Number.isFinite(x)) return String(x);
  if (x === 0) return "0";
  const a = Math.abs(x);
  if (a >= 1e4 || a < 1e-3) return x.toExponential(digits - 1);
  return x.toPrecision(digits);
}

export function ms(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)} s` : `${n} ms`;
}
