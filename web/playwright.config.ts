import { defineConfig } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
const dir =
  process.env.HARNESS_BROWSER_DATA_DIR ||
  mkdtempSync(join(tmpdir(), "harness-browser-"));
const py =
  process.env.HARNESS_PYTHON ||
  (process.platform === "win32"
    ? "../.venv/Scripts/python.exe"
    : "../.venv/bin/python");
export default defineConfig({
  testDir: "tests",
  workers: 1,
  use: { baseURL: "http://127.0.0.1:5173" },
  webServer: [
    {
      command: `"${py}" -m uvicorn inventory_service.main:create_app --factory --port 8002`,
      url: "http://127.0.0.1:8002/health/ready",
      env: { DB_PATH: join(dir, "inventory.db") },
    },
    {
      command: `"${py}" -m uvicorn order_service.main:create_app --factory --port 8001`,
      url: "http://127.0.0.1:8001/health/ready",
      env: {
        DB_PATH: join(dir, "orders.db"),
        INVENTORY_URL: "http://127.0.0.1:8002",
      },
    },
    {
      command: "npm run dev -- --port 5173 --strictPort",
      url: "http://127.0.0.1:5173",
    },
  ],
});
