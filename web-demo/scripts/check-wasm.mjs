// Fails fast with instructions if the wasm-pack output the app imports is missing.
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const pkg = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "oracle-harness", "pkg");
const needed = ["oracle_harness.js", "oracle_harness_bg.wasm", "oracle_harness.d.ts"];
const missing = needed.filter((f) => !existsSync(join(pkg, f)));
if (missing.length) {
  console.error(
    `Missing ${missing.join(", ")} in oracle-harness/pkg.\n` +
      "Build the resurrected BioUMAT wasm first:\n" +
      "  cd oracle-harness && wasm-pack build --target web   (or: npm run wasm)",
  );
  process.exit(1);
}
console.log("oracle-harness/pkg found");
