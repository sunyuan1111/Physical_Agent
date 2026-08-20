import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    chunkSizeWarningLimit: 1100,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) {
            return undefined;
          }
          const normalized = id.replace(/\\/g, "/");
          if (
            normalized.includes("/react/") ||
            normalized.includes("/react-dom/") ||
            normalized.includes("/scheduler/")
          ) {
            return "react-vendor";
          }
          if (normalized.includes("/@ant-design/x/")) {
            return "antd-x";
          }
          // antd widgets used ONLY on lazy-loaded pages. They have no eager
          // importer, so isolating them into their own chunk lets Rollup defer
          // it until a secondary page is opened, instead of forcing them into
          // the always-loaded antd-vendor chunk.
          if (
            normalized.includes("/antd/es/upload/") ||
            normalized.includes("/antd/lib/upload/") ||
            normalized.includes("/rc-upload/") ||
            normalized.includes("/antd/es/collapse/") ||
            normalized.includes("/antd/lib/collapse/") ||
            normalized.includes("/rc-collapse/") ||
            normalized.includes("/antd/es/input-number/") ||
            normalized.includes("/antd/lib/input-number/") ||
            normalized.includes("/rc-input-number/") ||
            normalized.includes("/@rc-component/mini-decimal/") ||
            normalized.includes("/antd/es/list/") ||
            normalized.includes("/antd/lib/list/")
          ) {
            return "antd-extras";
          }
          if (
            normalized.includes("/antd/") ||
            normalized.includes("/@ant-design/icons/") ||
            normalized.includes("/@ant-design/cssinjs/") ||
            normalized.includes("/@ant-design/colors/") ||
            normalized.includes("/@rc-component/") ||
            normalized.includes("/rc-")
          ) {
            return "antd-vendor";
          }
          if (
            normalized.includes("/react-markdown/") ||
            normalized.includes("/remark-") ||
            normalized.includes("/micromark") ||
            normalized.includes("/unified/") ||
            normalized.includes("/vfile/") ||
            normalized.includes("/hast") ||
            normalized.includes("/mdast") ||
            normalized.includes("/unist")
          ) {
            return "markdown-vendor";
          }
          return undefined;
        }
      }
    }
  },
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8766",
        changeOrigin: true
      }
    }
  }
});
