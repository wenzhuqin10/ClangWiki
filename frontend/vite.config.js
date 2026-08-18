import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
var root = fileURLToPath(new URL(".", import.meta.url));
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
                manualChunks: function (id) {
                    if (!id.includes("node_modules"))
                        return undefined;
                    if (id.includes("cytoscape") || id.includes("layout-base") || id.includes("cose-base"))
                        return "graph-vendor";
                    if (id.includes("react") || id.includes("scheduler"))
                        return "react-vendor";
                    if (id.includes("marked") || id.includes("dompurify"))
                        return "content-vendor";
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
