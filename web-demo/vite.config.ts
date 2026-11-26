import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The app imports the wasm-pack output (../oracle-harness/pkg), the Fortran
// source (../targets) and the orchestrator artefacts (../orchestrator/out), so
// the dev server must be allowed to read the repository root.
export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
  server: { fs: { allow: [".."] } },
  build: { target: "es2022", chunkSizeWarningLimit: 1024 },
});
