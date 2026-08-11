import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: false,
      },
    },
  },
  build: {
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules/viem") || id.includes("node_modules/ox") || id.includes("node_modules/@noble")) return "chain";
          if (id.includes("node_modules/lucide-react")) return "icons";
          if (id.includes("node_modules/react") || id.includes("node_modules/@tanstack")) return "react";
        },
      },
    },
  },
});
