import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      "/api/v1/orders": "http://127.0.0.1:8001",
      "/api/v1/products": "http://127.0.0.1:8002",
    },
  },
});
