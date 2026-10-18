import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  timeout: 60000,
  expect: { timeout: 20000 },
  use: { baseURL: "http://127.0.0.1:5173", headless: true },
  workers: 1,
  reporter: [["list"], ["json", { outputFile: "test-results/results.json" }]],
});
