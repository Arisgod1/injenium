import { expect, test } from "@playwright/test";

async function navigateInApp(page: import("@playwright/test").Page, label: string, path: string) {
  const bottomLink = page.locator(".bottom-nav").getByRole("link", { name: label });
  if (await bottomLink.isVisible()) {
    await bottomLink.click();
    return;
  }
  const directLink = page.locator(".primary-nav").getByRole("link", { name: label });
  if (!(await directLink.isVisible())) {
    await page.getByRole("button", { name: "打开导航" }).click();
  }
  await directLink.click();
  await expect(page).toHaveURL(path);
}

test("loads, validates, and simulates a built-in skill", async ({ page }) => {
  await page.goto("/market");
  await expect(page.getByRole("heading", { name: "技能市场" })).toBeVisible();
  await page.getByRole("button", { name: /门口巡检路线/ }).click();
  await page.getByRole("button", { name: "验证并装载" }).click();
  await expect(page.getByText("沙箱检查通过")).toBeVisible();
  await navigateInApp(page, "模拟实验室", "/lab");
  await page.getByRole("button", { name: "运行模拟" }).click();
  await expect(page.getByText("执行记录已就绪")).toBeVisible({ timeout: 5_000 });
});

test("imports Recipe JSON and blocks an unknown primitive", async ({ page }) => {
  await page.goto("/market");
  const input = page.locator('input[type="file"]');
  await input.setInputFiles({
    name: "safe-recipe.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify({
      intent: "等待并保持安全姿态",
      preconditions: [],
      steps: [{ primitive: "wait", params: { seconds: 1 } }],
      success_criteria: "等待完成",
      schema_version: 1,
      payload: {},
    })),
  });
  await expect(page.getByText("验证通过并已装载")).toBeVisible();

  await input.setInputFiles({
    name: "dangerous-recipe.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify({
      intent: "不安全动作",
      preconditions: [],
      steps: [{ primitive: "run_shell", params: { command: "id" } }],
      success_criteria: "不应执行",
      schema_version: 1,
      payload: {},
    })),
  });
  await expect(page.getByText("Recipe 未装载", { exact: true })).toBeVisible();
  await expect(page.getByText(/未执行任何动作/)).toBeVisible();
});

test("reads the public testnet and explains a missing wallet", async ({ page }) => {
  await page.goto("/market");
  await page.getByRole("button", { name: "测试网" }).click();
  await expect(page.getByText(/Chain ID 1439/)).toBeVisible();
  await expect(page.locator(".skill-row").first()).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "连接钱包" }).click();
  await expect(page.getByText("钱包未连接", { exact: true })).toBeVisible();
  await expect(page.getByText(/未检测到注入式 EVM 钱包/)).toBeVisible();
});

test("completes the local bounty flow", async ({ page }) => {
  await page.goto("/market");
  await page.getByRole("button", { name: /门口巡检路线/ }).click();
  await page.getByRole("button", { name: "验证并装载" }).click();
  await navigateInApp(page, "悬赏市场", "/requests");
  await page.getByRole("button", { name: "发布悬赏" }).click();
  await page.getByRole("button", { name: "锁定预算并发布" }).click();
  await expect(page.getByText("通过狭窄的装卸坡道并保持稳定")).toBeVisible();
  await page.getByRole("button", { name: "用已装载技能报价" }).click();
  await expect(page.getByRole("button", { name: "验收并执行" })).toBeVisible();
  await page.getByRole("button", { name: "验收并执行" }).click();
  await expect(page.getByRole("button", { name: "释放托管" })).toBeVisible();
  await page.getByRole("button", { name: "释放托管" }).click();
  await expect(page.getByRole("button", { name: "评分 5" })).toBeVisible();
});

test("keeps mainnet writes locked by default", async ({ page }) => {
  await page.goto("/market");
  await page.getByRole("button", { name: "主网" }).click();
  await expect(page.getByText(/主网合约尚未配置|主网只读保护已开启/)).toBeVisible();
});
