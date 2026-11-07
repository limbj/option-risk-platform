import { expect, test, type Locator, type Page } from "@playwright/test";
import sample from "../../examples/demo_inputs.json" with { type: "json" };
import type { Run, Total } from "../src/types";

test.setTimeout(30_000);

type ChartElement = HTMLElement & {
  data: Array<{
    type: string;
    x?: number[] | string[];
    y?: string[];
    z?: number[][];
    zmin?: number;
    zmax?: number;
    zmid?: number;
  }>;
  _fullLayout: {
    width: number;
    xaxis: { range: number[]; visible: boolean };
  };
};

function total(
  index: number,
  name: string,
  pnl: number | null,
  complete = true,
): Total {
  return {
    scenario_index: index,
    scenario_name: name,
    complete,
    value: pnl === null ? null : 1000 + pnl,
    pnl,
    ml_complete: false,
    ml_value: null,
    ml_pnl: null,
  };
}

async function openChart(page: Page, totals: Total[]) {
  const unexpectedRequests: string[] = [];
  const report: Run = {
    id: "chart-fixture-run",
    status: totals.every((row) => row.complete && row.pnl !== null)
      ? "COMPLETED"
      : "PARTIAL_ERROR",
    mode: "REFERENCE",
    created_at: "2025-10-04T09:00:00Z",
    elapsed_seconds: 0.1,
    progress: { completed: totals.length, total: totals.length, failed: 0 },
    totals,
    results: [],
  };
  const responses: Record<string, unknown> = {
    "/api/session/": {
      authenticated: true,
      user: { id: 1, username: "chart-test" },
      csrfToken: "chart-test-only",
      localDemoMode: true,
    },
    "/api/sample/": sample,
    "/api/inputs/": { items: [] },
    "/api/models/": { items: [] },
    "/api/runs/": { items: [report] },
    "/api/runs/chart-fixture-run/": report,
  };
  // All API traffic is intercepted; these chart fixtures never create stored runs.
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() === "GET" && path in responses) {
      await route.fulfill({ json: responses[path] });
    } else {
      unexpectedRequests.push(`${route.request().method()} ${path}`);
      await route.fulfill({
        status: 404,
        json: { detail: "Unmocked chart request" },
      });
    }
  });
  await page.goto("/");
  await page
    .getByRole("button", { name: "평가 · 실행 이력", exact: true })
    .click();
  await page.locator(".run-item").first().click();
  const chart = page.locator(".stress-chart.js-plotly-plot");
  await expect(chart).toBeVisible();
  await expect
    .poll(() =>
      chart.evaluate((element) =>
        Boolean((element as ChartElement)._fullLayout),
      ),
    )
    .toBe(true);
  expect(unexpectedRequests).toEqual([]);
  return chart;
}

async function renderedChart(chart: Locator) {
  return chart.evaluate((element) => {
    const plot = element as ChartElement;
    return {
      data: plot.data,
      range: plot._fullLayout.xaxis.range,
      axisVisible: plot._fullLayout.xaxis.visible,
      width: plot._fullLayout.width,
      containerWidth: plot.clientWidth,
    };
  });
}

test("up to eight scenarios use symmetric bars and keep missing values distinct from zero", async ({
  page,
}) => {
  const longName = "long-positive-scenario-with-a-full-name-in-the-tooltip";
  const chart = await openChart(page, [
    total(0, "base", 0),
    total(1, longName, 125.25),
    total(2, "loss", -250),
    total(3, "small-gain", 0.5),
    total(4, "gain", 80),
    total(5, "small-loss", -25),
    total(6, "incomplete-with-a-number", 999, false),
    total(7, "missing-pnl", null),
  ]);
  await expect(chart).toHaveAttribute(
    "aria-label",
    /막대그래프.*0 중심 대칭 축/,
  );
  const plot = await renderedChart(chart);
  expect(plot.data).toHaveLength(1);
  expect(plot.data[0].type).toBe("bar");
  expect(plot.data[0].x).toEqual([0, 125.25, -250, 0.5, 80, -25]);
  expect(plot.data[0].y).not.toContain("incomplete-with-a-number");
  expect(plot.data[0].y).not.toContain("missing-pnl");
  expect(plot.range[0]).toBe(-plot.range[1]);
  expect(plot.range[1]).toBeGreaterThanOrEqual(250);
  await expect(
    chart.getByText("미완료 시나리오 2개 제외", { exact: true }),
  ).toBeVisible();
  const bar = chart.locator(".barlayer .point").nth(1);
  await bar.scrollIntoViewIfNeeded();
  const bounds = await bar.boundingBox();
  expect(bounds).not.toBeNull();
  // Plotly receives pointer movement on its transparent drag layer above the bars.
  await page.mouse.move(
    bounds!.x + bounds!.width / 2,
    bounds!.y + bounds!.height / 2,
  );
  await expect(chart.locator(".hoverlayer")).toContainText(longName);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(async () => {
      const resized = await renderedChart(chart);
      return Math.abs(resized.width - resized.containerWidth);
    })
    .toBeLessThan(1);
  const mobile = await renderedChart(chart);
  expect(mobile.width).toBeLessThan(390);
  expect(mobile.range[0]).toBe(-mobile.range[1]);
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
});

test("nine scenarios retain a heatmap with a symmetric scale even when one result is incomplete", async ({
  page,
}) => {
  const values = [-400, -300, -200, -100, 0, 100, 200, 300, null];
  const chart = await openChart(
    page,
    values.map((value, index) => total(index, `scenario-${index}`, value)),
  );
  await expect(chart).toHaveAttribute("aria-label", /히트맵.*0 중심 대칭 색상/);
  const plot = await renderedChart(chart);
  expect(plot.data).toHaveLength(1);
  expect(plot.data[0].type).toBe("heatmap");
  expect(plot.data[0].z).toEqual([[-400, -300, -200, -100, 0, 100, 200, 300]]);
  expect(plot.data[0].x).not.toContain("scenario-8");
  expect(plot.data[0].zmin).toBe(-400);
  expect(plot.data[0].zmax).toBe(400);
  expect(plot.data[0].zmid).toBe(0);
  await expect(
    chart.getByText("미완료 시나리오 1개 제외", { exact: true }),
  ).toBeVisible();
});

test("a run without complete P&L shows an empty state rather than zero-valued bars", async ({
  page,
}) => {
  const chart = await openChart(page, [
    total(0, "base", null, false),
    total(1, "stress", null, false),
  ]);
  const plot = await renderedChart(chart);
  expect(plot.data).toEqual([]);
  expect(plot.axisVisible).toBe(false);
  await expect(
    chart.getByText("완료된 시나리오가 아직 없습니다.", { exact: true }),
  ).toBeVisible();
});
