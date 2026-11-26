import { useEffect, useState } from "react";
import { Dashboard } from "./components/Dashboard";
import { Lab } from "./components/Lab";

type Tab = "dashboard" | "lab";

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "dashboard", label: "Graveyard & Swarm Dashboard", icon: "🪦" },
  { id: "lab", label: "Live WASM BioUMAT Lab", icon: "🧬" },
];

function tabFromHash(): Tab {
  return window.location.hash === "#lab" ? "lab" : "dashboard";
}

export default function App() {
  const [tab, setTab] = useState<Tab>(tabFromHash);

  useEffect(() => {
    const onHash = () => setTab(tabFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  return (
    <div className="mx-auto flex max-w-[1600px] flex-col gap-6 px-4 py-6 md:px-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-bold tracking-wide text-bone-50 md:text-4xl">
            Necro<span className="text-ecto-400 drop-shadow-[0_0_12px_rgb(111_240_154/0.5)]">Fort</span>
          </h1>
          <p className="mt-1 max-w-3xl text-sm text-bone-300">
            Fortran 77 BioUMAT, resurrected into memory-safe Rust and WebAssembly, and proven against the original compiled with{" "}
            <code className="kbd">gfortran -std=legacy</code> by property-based differential testing.
          </p>
        </div>
        <nav className="flex gap-1 rounded-xl border border-crypt-700 bg-crypt-900/80 p-1" role="tablist">
          {TABS.map((t) => (
            <a
              key={t.id}
              href={t.id === "lab" ? "#lab" : "#"}
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => setTab(t.id)}
              className={`rounded-lg px-3.5 py-2 text-sm font-medium transition ${tab === t.id ? "bg-ecto-900/70 text-ecto-300 shadow-[inset_0_0_0_1px_rgb(52_217_120/0.4)]" : "text-bone-300 hover:text-bone-50"}`}
            >
              <span className="mr-1.5">{t.icon}</span>
              {t.label}
            </a>
          ))}
        </nav>
      </header>
      <main>{tab === "dashboard" ? <Dashboard /> : <Lab />}</main>
      <footer className="border-t border-crypt-800 pt-4 text-xs text-bone-500">
        MIT · Target: BioUMAT © 2019 Seyed Shayan Sajjadinia (MIT), untouched in <code>targets/bioumat/</code> · Kiroween 2026
      </footer>
    </div>
  );
}
