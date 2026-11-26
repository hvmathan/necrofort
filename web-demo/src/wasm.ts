// Loads the real wasm-pack output of oracle-harness (the resurrected BioUMAT).
import init, * as necro from "../../oracle-harness/pkg/oracle_harness.js";
import wasmUrl from "../../oracle-harness/pkg/oracle_harness_bg.wasm?url";

export type Necro = typeof necro;

export interface WasmInfo {
  api: Necro;
  bytes: number;
  loadMs: number;
}

let loading: Promise<WasmInfo> | null = null;

export function loadWasm(): Promise<WasmInfo> {
  loading ??= (async () => {
    const t0 = performance.now();
    const res = await fetch(wasmUrl);
    const buf = await res.arrayBuffer();
    await init({ module_or_path: buf });
    return { api: necro, bytes: buf.byteLength, loadMs: performance.now() - t0 };
  })();
  return loading;
}
