import { fileURLToPath } from "node:url";
import path from "node:path";

import { defineConfig } from "vite";

const terminalRoot = path.dirname(fileURLToPath(import.meta.url));
const staticRoot = path.resolve(
  terminalRoot,
  "../src/the_compute_bazaar/terminal/static",
);

export default defineConfig({
  base: "/terminal-assets/perspective/",
  publicDir: false,
  resolve: {
    alias: [
      "client",
      "server",
      "viewer",
      "viewer-charts",
      "viewer-datagrid",
    ].map((packageName) => ({
      find: `@perspective-dev/${packageName}`,
      replacement: path.join(
        terminalRoot,
        "node_modules/@perspective-dev",
        packageName,
      ),
    })),
  },
  build: {
    target: "esnext",
    sourcemap: false,
    outDir: path.join(staticRoot, "perspective"),
    emptyOutDir: true,
    rollupOptions: {
      input: path.join(staticRoot, "app.js"),
      output: {
        entryFileNames: "app.js",
        chunkFileNames: "chunks/[name]-[hash].js",
        assetFileNames: (asset) =>
          asset.names.some((name) => name.endsWith(".css"))
            ? "app.css"
            : "assets/[name]-[hash][extname]",
      },
    },
  },
});
