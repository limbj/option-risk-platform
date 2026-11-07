import { useEffect, useRef } from "react";
import type { Total } from "./types";

export default function StressChart({ totals }: { totals: Total[] }) {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let disposed = false;
    const element = root.current!;
    import("plotly.js-dist-min").then(({ default: Plotly }) => {
      if (disposed) return;
      const valid = totals.filter((row) => row.complete && row.pnl !== null);
      return Plotly.react(
        element,
        [
          {
            type: "heatmap",
            x: valid.map((x) => x.scenario_name),
            y: ["Stress P&L · USD"],
            z: [valid.map((x) => x.pnl)],
            zmid: 0,
            colorscale: [
              [0, "#c84e53"],
              [0.5, "#f6f4ed"],
              [1, "#21816a"],
            ],
            hovertemplate: "%{x}<br>%{z:,.2f} USD<extra></extra>",
            colorbar: { thickness: 12 },
          },
        ],
        {
          height: 240,
          margin: { l: 30, r: 20, t: 20, b: 90 },
          paper_bgcolor: "transparent",
          plot_bgcolor: "transparent",
          font: { family: "system-ui", size: 11 },
          yaxis: { showticklabels: false },
          xaxis: { automargin: true },
        },
        { responsive: true, displayModeBar: false },
      );
    });
    return () => {
      disposed = true;
      import("plotly.js-dist-min").then(({ default: Plotly }) =>
        Plotly.purge(element),
      );
    };
  }, [totals]);
  return <div ref={root} aria-label="완료된 시나리오 스트레스 손익 히트맵" />;
}
