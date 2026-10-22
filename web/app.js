"use strict";

const chartElement = document.getElementById("chart");
const button = document.getElementById("analyze-button");
const status = document.getElementById("load-status");
const source = document.getElementById("data-source");
const latest = document.getElementById("latest-candle");
const quality = document.getElementById("quality-status");
const count = document.getElementById("candle-count");
const signal = document.getElementById("signal-status");

// This preview never calculates a recommendation, including on error.
signal.textContent = "NO SIGNAL";

let candleSeries;
let chart;
if (window.LightweightCharts) {
  chart = LightweightCharts.createChart(chartElement, {
    autoSize: true,
    layout: { background: { type: "solid", color: "#111826" }, textColor: "#a9b7ca" },
    grid: { vertLines: { color: "#1d293a" }, horzLines: { color: "#1d293a" } },
    rightPriceScale: { borderColor: "#344158" },
    timeScale: { borderColor: "#344158", timeVisible: true, secondsVisible: false },
    localization: {
      timeFormatter: (time) => new Date(time * 1000).toISOString().slice(0, 16).replace("T", " ") + " UTC",
    },
  });
  candleSeries = chart.addSeries(LightweightCharts.CandlestickSeries, {
    upColor: "#25b89a", downColor: "#ef6a78", borderVisible: false,
    wickUpColor: "#25b89a", wickDownColor: "#ef6a78",
  });
}

async function refreshPreview() {
  button.disabled = true;
  status.classList.remove("error");
  status.textContent = "Loading historical preview…";
  source.textContent = "Local Silver · loading";
  quality.textContent = "Checking…";
  signal.textContent = "NO SIGNAL";
  try {
    if (!candleSeries) throw new Error("TradingView chart library is unavailable. Run npm ci --prefix web.");
    const response = await fetch("/api/preview", { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `Preview failed (HTTP ${response.status})`);
    candleSeries.setData(payload.candles);
    chart.timeScale().fitContent();
    source.textContent = "Local Silver · historical only";
    latest.textContent = payload.latest_candle_timestamp.replace("T", " ").replace("Z", " UTC");
    quality.textContent = payload.quality_status + (payload.missing_hours ? ` · ${payload.missing_hours} missing hours` : "");
    count.textContent = `${payload.candle_count} candles`;
    status.textContent = "Preview refreshed from local Silver. No live market data was fetched.";
  } catch (error) {
    if (candleSeries) candleSeries.setData([]);
    source.textContent = "Local Silver · unavailable";
    latest.textContent = "—";
    quality.textContent = "ERROR";
    count.textContent = "— candles";
    status.textContent = error instanceof Error ? error.message : "Unknown preview error";
    status.classList.add("error");
  } finally {
    button.disabled = false;
  }
}

button.addEventListener("click", refreshPreview);
refreshPreview();
