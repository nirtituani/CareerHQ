import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// .mts so the config is loaded as ESM. As a .ts file it is treated as CommonJS
// (package.json has no "type": "module"), which Vite warns about.
export default defineConfig({
  plugins: [react()],
  resolve: {
    // Native replacement for vite-tsconfig-paths: resolves the "@/*" alias
    // straight from tsconfig.json.
    tsconfigPaths: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    // e2e belongs to Playwright; it needs a running server.
    exclude: ["node_modules/**", ".next/**", "e2e/**"],
  },
});
