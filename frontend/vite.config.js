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
    },
    server: {
        host: "127.0.0.1",
        port: 5173,
        proxy: { "/api": "http://127.0.0.1:8082" },
    },
});
