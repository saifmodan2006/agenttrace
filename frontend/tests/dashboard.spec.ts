import { test, expect } from "@playwright/test";

test("create run, render real graph, investigate failure, inspect memory and history", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Execution overview" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "New agent run" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page
    .getByLabel("Execution goal")
    .fill("Browser test: repair the controlled calculator");
  await page.getByRole("button", { name: "Create & start run" }).click();
  await expect(
    page.getByRole("heading", { name: "Execution graph", exact: true }),
  ).toBeVisible();
  await expect(page.getByTestId("execution-graph")).toBeVisible();
  await expect(page.locator(".run-meta .badge")).toHaveText("completed", {
    timeout: 45000,
  });
  await expect(
    page.locator(".trace-node").filter({ hasText: "Validate calculator" }),
  ).toBeVisible();
  await page
    .locator(".trace-node")
    .filter({ hasText: "Validate calculator" })
    .click();
  await expect(page.getByLabel("Graph record details")).toBeVisible();
  await expect(
    page.getByText("Attempt history", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Preserved failures", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Highlight dependency paths" })
    .click();
  await expect(page.locator(".trace-node.highlight").first()).toBeVisible();
  await page.getByRole("button", { name: "Close details" }).click();
  await page.getByRole("button", { name: "Expand evidence" }).click();
  const decision = page
    .locator(".decision-card")
    .filter({ hasText: "apply approved patch" });
  await decision.click();
  await expect(
    page.getByText("Evidence at decision time", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Highlight evidence path" }).click();
  await page.getByRole("link", { name: "Failure investigation" }).click();
  await expect(
    page.getByRole("heading", { name: "addition-defect" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Memory explorer" }).click();
  await expect(
    page.getByRole("heading", { name: "calculator", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Search graph memory").fill("calculator");
  await page.getByRole("button", { name: "Search memory" }).click();
  await expect(
    page.getByRole("heading", { name: "calculator", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Run history" }).click();
  await expect(
    page
      .getByRole("button", {
        name: "Browser test: repair the controlled calculator",
      })
      .first(),
  ).toBeVisible();
  await page.getByRole("link", { name: "Agent activity" }).click();
  await expect(
    page.locator(".agent-card").filter({ hasText: "executor-api" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Connections" }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("responsive navigation, theme, and keyboard dialog escape", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Toggle navigation" }).click();
  await page.getByRole("button", { name: "Light appearance" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: "Dark appearance" }).click();
  await page.getByRole("link", { name: "Run history" }).click();
  await expect(
    page.getByRole("heading", { name: "Run history", exact: true }),
  ).toBeVisible();
  const size = await page.evaluate(() => ({
    width: document.documentElement.scrollWidth,
    viewport: innerWidth,
  }));
  expect(size.width).toBeLessThanOrEqual(size.viewport);
  await page.getByRole("button", { name: "New agent run" }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
});

test("authoritative updates survive reload", async ({ page }) => {
  await page.goto("/#graph");
  await expect(page.getByTestId("execution-graph")).toBeVisible();
  const before = await page.locator(".run-meta code").textContent();
  await page.reload();
  await expect(page.locator(".run-meta code")).toHaveText(before!);
  await expect(page.getByTestId("execution-graph")).toBeVisible();
});
