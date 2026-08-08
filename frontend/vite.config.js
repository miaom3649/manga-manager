/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
    plugins: [react()],
    test: {
        environment: "jsdom",
    },
    build: {
        outDir: "../src/hmanga/web",
        emptyOutDir: true,
    },
    server: {
        proxy: {
            "/api": "http://127.0.0.1:18459",
        },
    },
});
