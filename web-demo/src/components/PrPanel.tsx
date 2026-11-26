import { useState } from "react";
import type { PrInfo } from "../types";
import { Chip } from "./ui";

interface LivePr {
  number: number;
  html_url: string;
  state: string;
  draft: boolean;
  merged_at: string | null;
  title: string;
  updated_at: string;
  head: { ref: string; sha: string };
}

/** PR status as recorded by the orchestrator, with an optional live refresh. */
export function PrPanel({ pr, repo }: { pr: PrInfo | null; repo: string }) {
  const [live, setLive] = useState<LivePr | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const number = live?.number ?? pr?.number;

  const refresh = async () => {
    if (!number) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch(`https://api.github.com/repos/${repo}/pulls/${number}`, {
        headers: { Accept: "application/vnd.github+json" },
      });
      if (!r.ok) throw new Error(`GitHub API ${r.status}`);
      setLive((await r.json()) as LivePr);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const state = live ? (live.merged_at ? "merged" : live.state) : pr?.state;
  const draft = live ? live.draft : pr?.draft;
  const title = live?.title ?? pr?.title ?? pr?.payload.title;
  const url = live?.html_url ?? pr?.html_url;
  const sha = live?.head.sha ?? pr?.head_sha;
  const tone = state === "merged" ? "spirit" : state === "open" ? "ecto" : state === "closed" ? "blood" : "bone";

  return (
    <div className="flex h-full flex-col gap-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone={tone}>{state ?? "unknown"}</Chip>
        {draft && <Chip tone="ember">draft</Chip>}
        {number && <span className="font-mono text-bone-300">#{number}</span>}
        <Chip>{live ? "live from GitHub" : `recorded (${pr?.mode ?? "n/a"})`}</Chip>
      </div>
      <p className="font-medium text-bone-50">{title}</p>
      {sha && <p className="font-mono text-xs text-bone-500">head {sha.slice(0, 10)}</p>}
      {pr?.mode === "dry-run" && (
        <pre className="scroll-thin max-h-40 overflow-auto rounded-lg border border-crypt-700 bg-crypt-950 p-2 text-[11px] whitespace-pre-wrap text-bone-300">
          {pr.payload.body}
        </pre>
      )}
      <div className="mt-auto flex flex-wrap items-center gap-2">
        {url && (
          <a href={url} target="_blank" rel="noreferrer" className="rounded-lg border border-ecto-500/50 bg-ecto-900/40 px-3 py-1.5 text-xs font-medium text-ecto-300 hover:bg-ecto-900/70">
            Open on GitHub ↗
          </a>
        )}
        {number && (
          <button type="button" onClick={refresh} disabled={busy} className="rounded-lg border border-crypt-600 bg-crypt-800 px-3 py-1.5 text-xs text-bone-300 hover:border-crypt-500 disabled:opacity-50">
            {busy ? "Refreshing…" : "Refresh live status"}
          </button>
        )}
        {err && <span className="text-xs text-blood-300">{err}</span>}
      </div>
    </div>
  );
}
