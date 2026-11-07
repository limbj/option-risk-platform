import { test, expect, type Page } from "@playwright/test";

async function expectNoPageOverflow(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(() =>
        Math.max(
          document.body.scrollWidth,
          document.documentElement.scrollWidth,
        ),
      ),
    )
    .toBeLessThanOrEqual(page.viewportSize()!.width);
}

test("login, immutable input, reference valuation, compare, export and responsive layout", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  if (process.env.LOCAL_DEMO_MODE === "true") {
    await expect(page.getByText("로컬 작업공간 · 자동 진입")).toBeVisible();
    await expect(page.getByLabel("비밀번호")).toHaveCount(0);
  } else {
    if (!process.env.DEMO_PASSWORD)
      throw new Error("DEMO_PASSWORD required for authenticated mode");
    await page
      .getByLabel("사용자 이름")
      .fill(process.env.DEMO_USERNAME ?? "demo");
    await page.getByLabel("비밀번호").fill(process.env.DEMO_PASSWORD);
    await page.getByRole("button", { name: "실험실 열기" }).click();
  }
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
  await page.getByRole("link", { name: "JSON 다운로드" }).click();
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
    page.getByRole("heading", { name: "Heston 기준 모델과 MLP 비교" }),
  ).toBeVisible();

  const navigation = page.getByRole("navigation", { name: "주요 화면" });
  const reportSelector = page.getByLabel("검증 보고서 모델");
  const lastReportId = await reportSelector
    .locator("option")
    .last()
    .getAttribute("value");
  // CI may register one artifact; locally exercise a second version when available.
  for (const reportId of new Set([artifactId!, lastReportId!])) {
    await reportSelector.selectOption(reportId);
    await expect(page.locator(".artifact-id")).toHaveCount(1);
    await expect(page.locator(".artifact-id")).toContainText(reportId);
  }
  await page.getByRole("button", { name: "이 모델로 비교" }).click();
  await expect(page.getByLabel("실행 모드")).toHaveValue("COMPARE");
  await expect(page.getByLabel("ML 모델 버전")).toHaveValue(lastReportId!);
  await navigation.getByRole("button", { name: "ML 검증" }).click();
  const tabs = ["포지션", "시장 · 시나리오", "평가 · 실행 이력", "ML 검증"];
  for (const width of [1440, 1024, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    for (const tab of tabs) {
      await test.step(`${width}px: ${tab} navigation and page overflow`, async () => {
        const button = navigation.getByRole("button", { name: tab });
        await button.click();
        await expect(button).toHaveAttribute("aria-current", "page");
        await expect(button).toBeInViewport();
        await expectNoPageOverflow(page);
      });
    }
  }
  await page.screenshot({ path: "../work/ui-mobile.png", fullPage: true });

  // Navigation and wide financial tables must remain reachable with a keyboard.
  const positions = navigation.getByRole("button", { name: "포지션" });
  const market = navigation.getByRole("button", { name: "시장 · 시나리오" });
  await positions.focus();
  await page.keyboard.press("Tab");
  await expect(market).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(market).toHaveAttribute("aria-current", "page");
  await positions.focus();
  await page.keyboard.press("Enter");
  const contracts = page.getByRole("region", { name: "옵션 계약 표" });
  await contracts.focus();
  await expect(contracts).toBeFocused();
  if (
    await contracts.evaluate(
      (element) => element.scrollWidth > element.clientWidth,
    )
  ) {
    await page.keyboard.press("ArrowRight");
    await expect
      .poll(() => contracts.evaluate((element) => element.scrollLeft))
      .toBeGreaterThan(0);
  }
  const lastColumn = contracts.getByRole("columnheader").last();
  await lastColumn.scrollIntoViewIfNeeded();
  await expect(lastColumn).toBeInViewport({ ratio: 0.9 });
  await expectNoPageOverflow(page);
  expect(errors).toEqual([]);
});
