import { useEffect, useRef } from "react";

declare global {
  interface Window {
    TradingView?: {
      widget: new (options: Record<string, unknown>) => unknown;
    };
  }
}

const TV_SCRIPT_SRC = "https://s3.tradingview.com/tv.js";

function instrumentToTV(instrument?: string): string {
  // OANDA pairs are formatted like "USD_JPY" → "OANDA:USDJPY"
  if (!instrument) return "OANDA:USDJPY";
  return `OANDA:${instrument.replace("_", "")}`;
}

function granularityToInterval(g?: string): string {
  // TradingView uses minute count for intraday, letter for daily+
  switch (g) {
    case "M1": return "1";
    case "M5": return "5";
    case "M15": return "15";
    case "M30": return "30";
    case "H1": return "60";
    case "H4": return "240";
    case "D": return "D";
    case "W": return "W";
    case "M": return "M";
    default: return "60";
  }
}

function loadTVScript(): Promise<void> {
  if (window.TradingView) return Promise.resolve();
  const existing = document.querySelector(
    `script[src="${TV_SCRIPT_SRC}"]`
  ) as HTMLScriptElement | null;
  if (existing) {
    return new Promise((resolve, reject) => {
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject(new Error("tv.js load failed")));
    });
  }
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = TV_SCRIPT_SRC;
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("tv.js load failed"));
    document.head.appendChild(s);
  });
}

interface Props {
  instrument?: string;
  granularity?: string;
}

export default function LiveChart({ instrument, granularity }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  // Use a stable id so multiple mounts don't collide
  const containerId = "tv_live_chart";

  useEffect(() => {
    let cancelled = false;
    const symbol = instrumentToTV(instrument);
    const interval = granularityToInterval(granularity);

    void loadTVScript()
      .then(() => {
        if (cancelled) return;
        if (!containerRef.current || !window.TradingView) return;
        // Clear any previous widget before recreating
        containerRef.current.innerHTML = "";
        // The widget mounts inside the element with `container_id`
        const inner = document.createElement("div");
        inner.id = containerId;
        inner.style.height = "100%";
        inner.style.width = "100%";
        containerRef.current.appendChild(inner);
        new window.TradingView.widget({
          autosize: true,
          symbol,
          interval,
          timezone: "Etc/UTC",
          theme: "dark",
          style: "1",
          locale: "en",
          enable_publishing: false,
          hide_top_toolbar: false,
          hide_side_toolbar: false,
          hide_legend: false,
          allow_symbol_change: false,
          save_image: false,
          studies: [
            "MASimple@tv-basicstudies",
            "MASimple@tv-basicstudies",
          ],
          container_id: containerId,
          backgroundColor: "#0a0a0a",
          gridColor: "#262626",
        });
      })
      .catch(() => {
        if (cancelled || !containerRef.current) return;
        containerRef.current.innerHTML =
          '<div class="text-sm text-danger p-4">Failed to load TradingView. ' +
          "Check network / ad-blockers.</div>";
      });
    return () => {
      cancelled = true;
    };
  }, [instrument, granularity]);

  return (
    <div className="panel p-2 flex flex-col" style={{ height: 540 }}>
      <div className="flex items-center justify-between px-2 py-1 mb-1">
        <div className="text-sm font-bold text-neutral-200">
          Live chart — {instrument ?? "?"}{" "}
          <span className="text-muted font-normal">
            ({granularity ?? "?"})
          </span>
        </div>
        <a
          href={`https://www.tradingview.com/chart/?symbol=${instrumentToTV(
            instrument
          )}`}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-muted hover:text-neutral-200"
        >
          open in tradingview ↗
        </a>
      </div>
      <div
        ref={containerRef}
        style={{ flex: 1, minHeight: 480 }}
        className="rounded-md overflow-hidden"
      />
    </div>
  );
}
