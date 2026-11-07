import { test, expect } from "@playwright/test";

test("login, immutable input, reference valuation, compare, export and responsive layout", async ({
  page,
  request,
}) => {
  if (!process.env.DEMO_PASSWORD)
    throw new Error("DEMO_PASSWORD must be supplied from local environment");
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page
    .getByLabel("사용자 이름")
    .fill(process.env.DEMO_USERNAME ?? "demo");
  await page.getByLabel("비밀번호").fill(process.env.DEMO_PASSWORD);
  await page.getByRole("button", { name: "실험실 열기" }).click();
  await expect(
    page.getByRole("heading", { name: "포트폴리오 구성" }),
  ).toBeVisible();
  await expect(page.getByLabel("수량 2", { exact: true })).toHaveValue("-5");
  await page.screenshot({ path: "../work/ui-positions.png", fullPage: true });

  // A CSV import must retain the short sign and survive server-side validation.
  await page.locator("input[type=file]").setInputFiles({
    name: "positions.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(
      "option_type,strike,expiry,side,quantity,multiplier\ncall,100,2027-11-08,long,10,100\nput,95,2027-05-08,short,-5,100\n",
    ),
  });
  await expect(page.getByLabel("수량 2", { exact: true })).toHaveValue("-5");
  await page.getByRole("button", { name: "입력 버전 저장" }).click();
  await expect(page.getByRole("status")).toContainText(
    "입력 버전을 저장했습니다",
  );
  await page.getByRole("button", { name: "평가 실행" }).click();
  await expect(
    page.getByRole("heading", { name: /평가 결과 완료/ }),
  ).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("4 / 4 셀 처리 · 실패 0")).toBeVisible();
  await expect(page.locator(".js-plotly-plot")).toBeVisible();
  await page.screenshot({ path: "../work/ui-reference.png", fullPage: true });
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "JSON ↓" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/\.json$/);

  await page
    .getByRole("button", { name: "시장 · 시나리오", exact: false })
    .first()
    .click();
  await page.getByLabel("실행 모드").selectOption("COMPARE");
  const options = page.getByLabel("ML 모델 버전").locator("option");
  await expect(options.nth(1)).toHaveAttribute("value", /.+/);
  const artifactId = await options.nth(1).getAttribute("value");
  await page.getByLabel("ML 모델 버전").selectOption(artifactId!);
  await page.getByRole("button", { name: "평가 실행" }).click();
  await expect(
    page.getByRole("heading", { name: /평가 결과 완료/ }),
  ).toBeVisible({ timeout: 60_000 });
  await expect(
    page.getByRole("columnheader", { name: "ML P&L", exact: true }),
  ).toBeVisible();
  await page.screenshot({ path: "../work/ui-compare.png", fullPage: true });

  await page
    .getByRole("button", { name: "ML 검증", exact: false })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "같은 조건, 두 개의 가격." }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "../work/ui-mobile.png", fullPage: true });
  const width = await page.evaluate(() => ({
    body: document.body.scrollWidth,
    viewport: window.innerWidth,
  }));
  expect(width.body).toBeLessThanOrEqual(width.viewport);
  expect(errors).toEqual([]);
});
