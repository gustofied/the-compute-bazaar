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
      ...[
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
      {
        find: "@xterm/xterm",
        replacement: path.join(terminalRoot, "node_modules/@xterm/xterm"),
      },
      {
        find: "@xterm/addon-fit",
        replacement: path.join(terminalRoot, "node_modules/@xterm/addon-fit"),
      },
      {
        find: "uplot",
        replacement: path.join(terminalRoot, "node_modules/uplot"),
      },
    ],
  },
  build: {
    target: "esnext",
    sourcemap: false,
    outDir: path.join(staticRoot, "perspective"),
    emptyOutDir: true,
    rollupOptions: {
      input: {
        app: path.join(staticRoot, "app.js"),
        command: path.join(staticRoot, "command.js"),
        fleet: path.join(staticRoot, "fleet.js"),
      },
      output: {
        entryFileNames: "[name].js",
        chunkFileNames: "chunks/[name]-[hash].js",
        assetFileNames: (asset) =>
          asset.names.some((name) => name.endsWith(".css"))
            ? "[name][extname]"
            : "assets/[name]-[hash][extname]",
      },
    },
  },
});
