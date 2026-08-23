import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: resolve(root, "../clangwiki/web"),
    emptyOutDir: true,
    sourcemap: false,
    assetsDir: "assets",
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          const normalizedId = id.replace(/\\/g, "/");
          if (normalizedId.includes("cytoscape") || normalizedId.includes("layout-base") || normalizedId.includes("cose-base")) return "graph-vendor";
          // Match the React packages as package path segments. A broad
          // `includes("react")` also captures `@react-three/*`, which would
          // eagerly execute the optional 3D renderer during app startup.
          if (/(^|\/)(react|react-dom|scheduler)(\/|$)/.test(normalizedId)) return "react-vendor";
          if (id.includes("marked") || id.includes("dompurify")) return "content-vendor";
          return undefined;
        },
      },
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8082" },
  },
});
