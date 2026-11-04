import { defineConfig } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
const dir =
  process.env.HARNESS_BROWSER_DATA_DIR ||
  mkdtempSync(join(tmpdir(), "harness-browser-"));
export default defineConfig({
  testDir: "tests",
  workers: 1,
  use: { baseURL: "http://127.0.0.1:5173" },
  webServer: [
    {
      command: "node ../tools/harness.mjs serve inventory",
      url: "http://127.0.0.1:8002/health/ready",
      env: { DB_PATH: join(dir, "inventory.db") },
      timeout: 60000,
    },
    {
      command: "node ../tools/harness.mjs serve orders",
      url: "http://127.0.0.1:8001/health/ready",
      env: {
        DB_PATH: join(dir, "orders.db"),
        INVENTORY_URL: "http://127.0.0.1:8002",
      },
      timeout: 60000,
    },
    {
      command: "npm run dev -- --port 5173 --strictPort",
      url: "http://127.0.0.1:5173",
    },
  ],
});
