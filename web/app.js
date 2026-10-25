"use strict";

const element = (id) => document.getElementById(id);
const chartElement = element("chart");
const buttons = [element("analyze-button"), element("load-button"), element("preview-button")];
const status = element("load-status");
const signal = element("signal-status");
const modeBadge = element("mode-badge");
const source = element("data-source");
const latest = element("latest-candle");
const quality = element("quality-status");
const count = element("candle-count");
const freshness = element("freshness-status");
const expiry = element("signal-expiry");
const endpoints = {
  preview: "/api/preview",
  market: "/api/market",
  analyze: "/api/analyze",
};
let expiryAt = null;
let busy = false;
let candleSeries;
let chart;

if (window.LightweightCharts) {
  chart = LightweightCharts.createChart(chartElement, {
    autoSize: true,
    layout: { background: { type: "solid", color: "#111826" }, textColor: "#a9b7ca" },
    grid: { vertLines: { color: "#1d293a" }, horzLines: { color: "#1d293a" } },
    rightPriceScale: { borderColor: "#344158" },
    timeScale: { borderColor: "#344158", timeVisible: true, secondsVisible: false },
    localization: { timeFormatter: (time) => utc(new Date(time * 1000).toISOString()) },
  });
  candleSeries = chart.addSeries(LightweightCharts.CandlestickSeries, {
    upColor: "#25b89a", downColor: "#ef6a78", borderVisible: false,
    wickUpColor: "#25b89a", wickDownColor: "#ef6a78",
  });
}

function utc(value) {
  if (!value || !Number.isFinite(Date.parse(value))) return "—";
  return new Date(value).toISOString().replace("T", " ").replace(".000Z", " UTC");
}

function list(id, items) {
  const container = element(id);
  container.replaceChildren();
  for (const text of items || []) {
    const item = document.createElement("li");
    item.textContent = String(text);
    container.append(item);
  }
}

function clearAnalysis(message, historical = false) {
  expiryAt = null;
  signal.textContent = historical ? "NO SIGNAL" : "HOLD";
  signal.dataset.decision = "HOLD";
  expiry.textContent = "No current analysis";
  element("decision-note").textContent = message;
  element("strategy-name").textContent = "Not run";
  element("analysis-timestamp").textContent = "—";
  element("market-timestamp").textContent = "—";
  element("indicator-values").replaceChildren();
  clearReferenceLevels();
  list("decision-reasons", historical ? ["Historical preview produces no trading signal."] : []);
  list("analysis-warnings", []);
}

function clearReferenceLevels() {
  element("atr-value").textContent = "—";
  element("atr-method").textContent = "Not calculated";
  element("reference-prices").hidden = true;
  for (const id of ["entry-value", "stop-loss-value", "take-profit-value", "risk-reward-value"]) {
    element(id).textContent = "—";
  }
  element("reference-levels-note").textContent = "No current reference estimates.";
}

function renderReferenceLevels(payload) {
  clearReferenceLevels();
  const atr = payload.atr_14;
  if (!Number.isFinite(atr) || atr <= 0 || payload.atr_method !== "Wilder RMA (14)") {
    throw new Error("Valid Wilder ATR(14) is unavailable; no usable current assessment.");
  }
  const price = (value) => `${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USDT`;
  element("atr-value").textContent = price(atr);
  element("atr-method").textContent = payload.atr_method;
  if (payload.decision === "HOLD") {
    element("reference-levels-note").textContent = "No entry/SL/TP recommendations for HOLD.";
    return;
  }
  const levels = payload.reference_levels;
  const validPrices = levels && [levels.entry, levels.stop_loss, levels.take_profit].every((value) => Number.isFinite(value) && value > 0);
  if (!validPrices || atr <= 0 || levels.risk_reward !== "1:2" || levels.currency !== "USDT" || levels.atr_period !== 14 || levels.atr_method !== "Wilder RMA") {
    throw new Error("Reference levels are unavailable or invalid; no usable current assessment.");
  }
  const direction = payload.decision === "BUY" ? 1 : -1;
  const riskDistance = direction * (levels.entry - levels.stop_loss);
  const rewardDistance = direction * (levels.take_profit - levels.entry);
  const near = (actual, expected) => Math.abs(actual - expected) <= 1e-10 * Math.abs(expected);
  if (riskDistance <= 0 || rewardDistance <= 0 || !near(riskDistance, 1.5 * atr) || !near(rewardDistance, 3 * atr) || !near(rewardDistance, 2 * riskDistance)) {
    throw new Error("Reference levels do not match the ATR direction and 1:2 rule.");
  }
  element("entry-value").textContent = price(levels.entry);
  element("stop-loss-value").textContent = price(levels.stop_loss);
  element("take-profit-value").textContent = price(levels.take_profit);
  element("risk-reward-value").textContent = "1:2";
  element("reference-prices").hidden = false;
  element("reference-levels-note").textContent = "SL distance = 1.5 × ATR; TP distance = 3 × ATR. No order is placed.";
}

function setBusy(value) {
  busy = value;
  for (const button of buttons) button.disabled = value;
  chartElement.setAttribute("aria-busy", String(value));
}

function renderMarket(payload, historical) {
  if (!candleSeries) throw new Error("TradingView chart library is unavailable. Run npm ci --prefix web --ignore-scripts.");
  if (!Array.isArray(payload.candles) || !payload.candles.length) throw new Error("No validated candles were returned.");
  candleSeries.setData(payload.candles);
  chart.timeScale().fitContent();
  source.textContent = historical ? "Local Silver · historical only" : (payload.source || "Binance BTC/USDT Spot — Analysis Reference");
  latest.textContent = utc(payload.latest_candle_timestamp);
  quality.textContent = String(payload.quality_status || "Unknown") + (payload.missing_hours ? ` · ${payload.missing_hours} missing hours` : "");
  count.textContent = `${payload.candle_count ?? payload.candles.length} candles`;
  modeBadge.textContent = historical ? "HISTORICAL PREVIEW — NOT LIVE" : "REFERENCE DATA · DEMO / MANUAL EXECUTION";
  modeBadge.classList.toggle("reference-badge", !historical);
  element("chart-title").textContent = historical ? "Historical candlesticks" : "Completed BTC/USDT 1H reference candles";
  element("chart-description").textContent = historical ? "Read-only local Silver preview; no point-in-time trading eligibility." : "Binance Spot reference · completed candles only · no broker execution connection";
  const age = payload.data_freshness?.age_seconds;
  freshness.textContent = historical ? "Historical snapshot" : String(payload.data_freshness?.status || "Unknown") + (Number.isFinite(age) ? ` · ${Math.floor(age / 60)} min since close` : "");
}

function renderAnalysis(payload) {
  const decision = payload.decision;
  if (!["BUY", "SELL", "HOLD"].includes(decision)) throw new Error("Invalid analysis decision; no usable signal.");
  const deadline = Date.parse(payload.expires_at);
  if (decision !== "HOLD" && (!Number.isFinite(deadline) || deadline <= Date.now())) {
    throw new Error("Analysis is expired or has no valid expiry. Click Analyze Now again.");
  }
  renderReferenceLevels(payload);
  signal.textContent = decision;
  signal.dataset.decision = decision;
  expiryAt = Number.isFinite(deadline) ? deadline : null;
  element("decision-note").textContent = `${decision} — informational Binance Spot reference only. Position sizing and broker checks are disabled.`;
  element("strategy-name").textContent = String(payload.strategy || "Deterministic momentum baseline");
  element("market-timestamp").textContent = utc(payload.market_timestamp || payload.latest_candle_timestamp);
  element("analysis-timestamp").textContent = utc(payload.generated_at);
  list("decision-reasons", payload.explanations || []);
  list("analysis-warnings", payload.warnings || []);
  const indicators = element("indicator-values");
  indicators.replaceChildren();
  for (const [name, value] of Object.entries(payload.indicators || {})) {
    const item = document.createElement("div");
    const label = document.createElement("dt");
    const number = document.createElement("dd");
    label.textContent = name;
    number.textContent = Number.isFinite(value) ? value.toPrecision(6) : "Unavailable";
    item.append(label, number);
    indicators.append(item);
  }
  updateExpiry();
}

function updateExpiry() {
  if (!expiryAt) return;
  const remaining = Math.ceil((expiryAt - Date.now()) / 1000);
  if (remaining <= 0) {
    clearAnalysis("Previous assessment expired. HOLD — request fresh data with Analyze Now.");
    expiry.textContent = "Expired";
    freshness.textContent = "Refresh required";
    return;
  }
  expiry.textContent = `Expires ${utc(new Date(expiryAt).toISOString())} · ${remaining}s`;
}

async function request(mode) {
  if (busy) return;
  const historical = mode === "preview";
  setBusy(true);
  clearAnalysis(historical ? "Loading the historical preview…" : "HOLD — waiting for fresh completed-candle data and validation.", historical);
  status.classList.remove("error");
  status.textContent = historical ? "Loading historical preview…" : mode === "market" ? "Loading recent completed BTC 1H candles…" : "Fetching fresh completed candles and analyzing…";
  quality.textContent = "Checking…";
  freshness.textContent = "Checking…";
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 45000);
  try {
    const response = await fetch(endpoints[mode], {
      method: historical ? "GET" : "POST",
      cache: "no-store",
      signal: controller.signal,
      ...(historical ? {} : { headers: { "Content-Type": "application/json" }, body: "{}" }),
    });
    const payload = await response.json();
    if (!response.ok) {
      const reasons = payload.explanations?.join(" ") || "";
      throw new Error(payload.error || reasons || `Request failed (HTTP ${response.status})`);
    }
    renderMarket(payload, historical);
    if (mode === "analyze") {
      renderAnalysis(payload);
      status.textContent = "Fresh reference data analyzed. Informational signal only; place or skip any demo trade manually.";
    } else {
      clearAnalysis(historical ? "Historical preview only; no signal generated." : "Recent data loaded. Click Analyze Now for an informational assessment.", historical);
      status.textContent = historical ? "Preview refreshed from local Silver. No fresh market data was fetched." : "Recent reference candles loaded. No assessment has been generated.";
    }
  } catch (error) {
    clearAnalysis(historical ? "Historical preview unavailable." : "HOLD — data or analysis unavailable. No usable current assessment.", historical);
    if (candleSeries) candleSeries.setData([]);
    source.textContent = historical ? "Local Silver · unavailable" : "Binance reference · unavailable";
    latest.textContent = "—";
    count.textContent = "— candles";
    quality.textContent = "ERROR";
    freshness.textContent = "Unavailable";
    status.textContent = error?.name === "AbortError" ? "Request timed out. Click again to retry." : (error instanceof Error ? error.message : "Unknown request error");
    status.classList.add("error");
    list("decision-reasons", [status.textContent]);
  } finally {
    clearTimeout(timeout);
    setBusy(false);
  }
}

element("analyze-button").addEventListener("click", () => request("analyze"));
element("load-button").addEventListener("click", () => request("market"));
element("preview-button").addEventListener("click", () => request("preview"));
setInterval(updateExpiry, 1000);
request("preview");
