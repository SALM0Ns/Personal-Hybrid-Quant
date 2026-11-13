import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import Activity from 'lucide-react/dist/esm/icons/activity.js';
import ArrowDownRight from 'lucide-react/dist/esm/icons/arrow-down-right.js';
import ArrowUpRight from 'lucide-react/dist/esm/icons/arrow-up-right.js';
import BarChart3 from 'lucide-react/dist/esm/icons/chart-column.js';
import ChevronDown from 'lucide-react/dist/esm/icons/chevron-down.js';
import CircleHelp from 'lucide-react/dist/esm/icons/circle-help.js';
import Clock3 from 'lucide-react/dist/esm/icons/clock-3.js';
import Crosshair from 'lucide-react/dist/esm/icons/crosshair.js';
import Layers3 from 'lucide-react/dist/esm/icons/layers.js';
import RefreshCw from 'lucide-react/dist/esm/icons/refresh-cw.js';
import ShieldAlert from 'lucide-react/dist/esm/icons/shield-alert.js';
import SlidersHorizontal from 'lucide-react/dist/esm/icons/sliders-horizontal.js';
import Chart from './Chart';
import type { Analysis, Candle, Data, Indicator, Pattern, Swing, Visibility, Zone } from './types';
import { timeLabel, formatNumber, readable, getOrCreateAppRoot, DEFAULT_ANALYSIS_SETTINGS, ANALYSIS_SETTING_FIELDS, terminalParams, snapshotResponsesMatch, pricesCollapseAtPrecision, mt5CanShowSetup, snapshotChanged, setupDisplayState, setupDisplayLabel, needsFeedAttention, connectionLabel, summarizeFeedReasons, summarizeGapClassifications, brokerRiskMatchesSnapshot, parseRiskBudget, riskRequestParams, barsSinceConfirmation, type PatternLineMode, MT5_POLL_INTERVAL_MS, MT5_REQUEST_TIMEOUT_MS } from './utils';
import './styles.css';

type Base = { snapshot_sha256: string; source: string; symbol: string; timeframe: string; analysis_config?: Record<string, unknown> };
type Source = 'exness' | 'massive' | 'mt5';
type Mt5Status = { status: 'LIVE' | 'STALE' | 'OFFLINE' | 'UNVERIFIED' | 'MARKET_CLOSED'; reasons: string[]; snapshot_sha256: string | null; latest_completed_candle: string | null; last_ingestion_utc: string | null; heartbeat_age_seconds: number | null; target_quote_status: string | null; target_quote_age_seconds?: number | null; connection_status: string | null; unresolved_gap_count: number | null; history_count: number | null; current_segment_count: number | null; unresolved_revision_count?: number | null; gaps?: Array<{classification?: string | null}> | null };
type ExternalStatus = { provider: string; freshness: string; last_successful_fetch: string | null; latest_observed_candle: string | null; latest_completed_candle: string | null; provider_delay: string; error: string | null; snapshot_sha256: string | null; gap_count?: number | null };
type CandleResponse = Base & { candles: Candle[] };
type IndicatorResponse = Base & { indicators: Indicator[] };
type PatternResponse = Base & { swings: Swing[]; zones: Zone[]; patterns: Pattern[] };
type AnalysisResponse = Base & { analysis: Analysis | null };
type NativeComparison = { instrument: string; verification_status: string; comparisons: Array<{direction: string; case: string; comparison: {absolute_difference: string; relative_difference: string | null} | null}> };
type BrokerSpecification = { instrument: string; specification_status: string; verification_status: string;
  properties: Array<{instrument: string; name: string; value: string; status: string}>;
  assessment?: {freshness_status: string; native_calculation_status: string; problems: string[]}; };
type BrokerRisk = {
  instrument: string; timeframe: string; broker_source: string; account_type: string; requestKey?: string;
  specification_status: string; specification_snapshot_time: string | null;
  feed_quality_status: string; setup_status: string; snapshot_sha256: string | null;
  price_distance_reward_risk: number | null; gross_risk_reward: number | null; theoretical_volume: number | null; normalized_volume: number | null;
  expected_gross_loss: number | null; expected_gross_profit: number | null; margin_estimate: number | null; risk_budget: number | null;
  known_costs: {commission: number | null; spread: number | null; slippage: number | null; financing: number | null};
  blocking_reasons: string[]; warnings: string[];
};
const initialVisibility: Visibility = { ema20: true, ema50: true, zones: true, swings: true, patterns: true, levels: true };
const overlays: Array<[keyof Visibility, string, string]> = [['ema20', 'EMA 20', '#e5bb69'], ['ema50', 'EMA 50', '#9a94f7'], ['zones', 'S/R zones', '#6fc2ad'], ['swings', 'Swings', '#d5808b'], ['patterns', 'Patterns', '#a5b3c5'], ['levels', 'Trade levels', '#6ca7ff']];
async function api<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { const body = await response.json(); if (body.detail) message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail); } catch { /* Keep HTTP status when error isn't JSON. */ }
    throw new Error(message);
  }
  return await response.json() as T;
}
function Metric({ label, value, accent }: {label: string; value: React.ReactNode; accent?: string}) {
  return <div className="metric"><span>{label}</span><strong style={accent ? {color: accent} : undefined}>{value}</strong></div>;
}
function App() {
  const selectionRevision = useRef(0);
  const [source, setSource] = useState<Source>('mt5');
  const [externalStatus, setExternalStatus] = useState<ExternalStatus | null>(null);
  const [mt5Status, setMt5Status] = useState<Mt5Status | null>(null);
  const [nativeComparison, setNativeComparison] = useState<NativeComparison | null>(null);
  const [brokerSpecification, setBrokerSpecification] = useState<BrokerSpecification | null>(null);
  const [brokerRisk, setBrokerRisk] = useState<BrokerRisk | null>(null);
  const [brokerRiskError, setBrokerRiskError] = useState(false);
  const [riskBudgetInput, setRiskBudgetInput] = useState('');
  const [appliedRiskBudget, setAppliedRiskBudget] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [symbol, setSymbol] = useState('EURUSDm');
  const [timeframe, setTimeframe] = useState('H1');
  const [visibility, setVisibility] = useState(initialVisibility);
  const [patternLineMode, setPatternLineMode] = useState<PatternLineMode>('all');
  const [data, setData] = useState<Data | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const [focus, setFocus] = useState<Pattern | null>(null);
  const [settings, setSettings] = useState({...DEFAULT_ANALYSIS_SETTINGS});
  const [draft, setDraft] = useState(settings);
  const [sort, setSort] = useState<'recent' | 'type' | 'status'>('recent');
  useEffect(() => { setData(null); setFocus(null); setExternalStatus(null); setMt5Status(null); setError(''); }, [source, symbol, timeframe]);
  useEffect(() => {
    if (source !== 'massive') return;
    let alive = true; let lastIdentity: string | null = null;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const result = await api<ExternalStatus>(`/api/external/status?${new URLSearchParams({symbol, timeframe})}`, controller.signal);
        if (!alive) return;
        setExternalStatus(result);
        if (result.snapshot_sha256 && result.snapshot_sha256 !== lastIdentity) { lastIdentity = result.snapshot_sha256; setReload(n => n + 1); }
      } catch (err) {
        if (alive && !controller.signal.aborted) setExternalStatus(previous => ({provider: 'Massive', freshness: 'ERROR', last_successful_fetch: previous?.last_successful_fetch ?? null, latest_observed_candle: previous?.latest_observed_candle ?? null, latest_completed_candle: previous?.latest_completed_candle ?? null, provider_delay: 'end-of-day', snapshot_sha256: previous?.snapshot_sha256 ?? null, error: err instanceof Error ? err.message : 'Feed status unavailable'}));
      }
    };
    void poll(); const timer = window.setInterval(poll, 60_000);
    return () => { alive = false; controller.abort(); window.clearInterval(timer); };
  }, [source, symbol, timeframe]);
  useEffect(() => {
    if (source !== 'mt5') return;
    let alive = true; let inFlight = false; let lastIdentity: string | null = null; let lastStatus: string | null = null;
    const controller = new AbortController();
    const poll = async () => {
      if (inFlight) return;
      inFlight = true;
      const request = new AbortController();
      const relayAbort = () => request.abort();
      controller.signal.addEventListener('abort', relayAbort, {once: true});
      const deadline = window.setTimeout(() => request.abort(), MT5_REQUEST_TIMEOUT_MS);
      try {
        const result = await api<Mt5Status>(`/api/mt5/status?${new URLSearchParams({symbol, timeframe})}`, request.signal);
        if (!alive) return;
        setMt5Status(result);
        if (snapshotChanged(lastIdentity, result.snapshot_sha256) || (lastStatus !== null && lastStatus !== result.status && result.snapshot_sha256)) { lastIdentity = result.snapshot_sha256; setReload(n => n + 1); }
        lastStatus = result.status;
      } catch (err) {
        if (alive && !controller.signal.aborted) { lastStatus = 'UNVERIFIED'; setMt5Status(previous => ({
          status: 'UNVERIFIED', reasons: ['Cannot reach the bridge status endpoint; current feed health is unknown.'],
          snapshot_sha256: previous?.snapshot_sha256 ?? null, latest_completed_candle: previous?.latest_completed_candle ?? null,
          last_ingestion_utc: previous?.last_ingestion_utc ?? null, heartbeat_age_seconds: null, target_quote_status: 'UNVERIFIED',
          target_quote_age_seconds: null, connection_status: 'UNVERIFIED', unresolved_gap_count: previous?.unresolved_gap_count ?? null,
          history_count: previous?.history_count ?? null, current_segment_count: previous?.current_segment_count ?? null,
        })); }
      } finally { window.clearTimeout(deadline); controller.signal.removeEventListener('abort', relayAbort); inFlight = false; }
    };
    const onVisibility = () => {
      if (document.visibilityState === 'visible') {
        setMt5Status(previous => previous ? {...previous, status: 'UNVERIFIED', reasons: ['Rechecking bridge health after returning to this tab.']} : null);
        void poll();
      }
    };
    document.addEventListener('visibilitychange', onVisibility);
    void poll(); const timer = window.setInterval(poll, MT5_POLL_INTERVAL_MS);
    return () => { alive = false; controller.abort(); window.clearInterval(timer); document.removeEventListener('visibilitychange', onVisibility); };
  }, [source, symbol, timeframe]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    const params = terminalParams(source, symbol, timeframe, settings);
    Promise.all([
      api<CandleResponse>(`/api/candles?${params}`, controller.signal),
      api<IndicatorResponse>(`/api/indicators?${params}`, controller.signal),
      api<PatternResponse>(`/api/patterns?${params}`, controller.signal),
      api<AnalysisResponse>(`/api/analysis?${params}`, controller.signal),
    ]).then(([bars, indicators, patterns, analysis]) => {
      if (controller.signal.aborted) return;
      if (!snapshotResponsesMatch(bars, [indicators, patterns, analysis], {source, symbol, timeframe, settings})) throw new Error('Dataset identity or analysis settings changed during loading. Refresh to try again.');
      setData({ candles: bars.candles, indicators: indicators.indicators, swings: patterns.swings, zones: patterns.zones, patterns: patterns.patterns, analysis: analysis.analysis, snapshot_sha256: bars.snapshot_sha256, time_basis: source === 'massive' ? 'utc' : 'broker' });
    }).catch(err => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'Unable to load historical data.'); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [symbol, timeframe, source, reload, settings]);
  useEffect(() => {
    setBrokerSpecification(null);
    if (source !== 'mt5') return;
    const controller = new AbortController();
    api<BrokerSpecification>(`/api/broker-specification?symbol=${encodeURIComponent(symbol)}`, controller.signal)
      .then(value => { if (!controller.signal.aborted && value.instrument === symbol) setBrokerSpecification(value); })
      .catch(() => { if (!controller.signal.aborted) setBrokerSpecification(null); });
    return () => controller.abort();
  }, [source, symbol, reload]);
  useEffect(() => {
    setNativeComparison(null);
    if (source !== 'mt5') return;
    const controller = new AbortController();
    api<NativeComparison>(`/api/broker-native-comparison?symbol=${encodeURIComponent(symbol)}`, controller.signal)
      .then(value => { if (!controller.signal.aborted && value.instrument === symbol) setNativeComparison(value); })
      .catch(() => { if (!controller.signal.aborted) setNativeComparison(null); });
    return () => controller.abort();
  }, [source, symbol, reload]);
  const specValue = (key: string) => (brokerSpecification?.instrument === symbol ? brokerSpecification : null)?.properties.find(item => item.name === key && !item.status.startsWith('unavailable'))?.value || '—';
  useEffect(() => {
    setBrokerRisk(null); setBrokerRiskError(false);
    if (source !== 'mt5' || appliedRiskBudget === null) return;
    const controller = new AbortController();
    const params = riskRequestParams(source, symbol, timeframe, settings, appliedRiskBudget);
    api<BrokerRisk>(`/api/broker-risk?${params}`, controller.signal)
      .then(result => { if (!controller.signal.aborted) setBrokerRisk({...result, requestKey: params}); })
      .catch(() => { if (!controller.signal.aborted) { setBrokerRisk(null); setBrokerRiskError(true); } });
    return () => controller.abort();
  }, [source, symbol, timeframe, settings, reload, appliedRiskBudget]);
  const refresh = async () => {
    if (source !== 'massive') { setReload(n => n + 1); return; }
    const revision = selectionRevision.current;
    setRefreshing(true);
    try {
      const response = await fetch(`/api/external/refresh?${new URLSearchParams({symbol, timeframe})}`, { method: 'POST' });
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `Refresh failed (${response.status})`);
      const result = body as ExternalStatus;
      if (revision !== selectionRevision.current) return;
      setExternalStatus(result);
      if (result.snapshot_sha256 && result.snapshot_sha256 !== data?.snapshot_sha256) setReload(n => n + 1);
    } catch (err) {
      if (revision !== selectionRevision.current) return;
      setExternalStatus(previous => ({provider:'Massive', freshness:'ERROR', last_successful_fetch: previous?.last_successful_fetch ?? null, latest_observed_candle: previous?.latest_observed_candle ?? null, latest_completed_candle: previous?.latest_completed_candle ?? null, provider_delay:'end-of-day', snapshot_sha256:previous?.snapshot_sha256 ?? null, error:err instanceof Error ? err.message : 'Refresh failed'}));
    } finally { setRefreshing(false); }
  };
  const changeSelection = (kind: 'source' | 'symbol' | 'timeframe', value: string) => {
    selectionRevision.current += 1; setData(null); setExternalStatus(null); setMt5Status(null); setFocus(null); setError('');
    if (kind === 'source') { setSource(value as Source); if (value === 'massive' && timeframe === 'H4') setTimeframe('M15'); }
    else if (kind === 'symbol') setSymbol(value);
    else setTimeframe(value);
  };
  const isExternal = source === 'massive';
  const isMt5 = source === 'mt5';
  const mt5SetupAvailable = mt5CanShowSetup(mt5Status, data?.snapshot_sha256, loading, Boolean(error));
  const analysisReady = !loading && !error && (!isMt5 || mt5SetupAvailable);
  const clockLabel = (value: string | null | undefined) => timeLabel(value, isExternal ? 'utc' : 'broker');
  const displaySymbol = isExternal ? (symbol === 'EURUSDm' ? 'EUR/USD' : 'XAU/USD') : symbol;
  const patterns = useMemo(() => { const times = new Set(data?.candles.map(c => c.timestamp) ?? []); return [...(data?.patterns ?? [])].filter(p => times.has(p.anchor_1_timestamp) && times.has(p.anchor_2_timestamp)).sort((a, b) => sort === 'recent' ? b.detection_timestamp.localeCompare(a.detection_timestamp) : (sort === 'type' ? a.type.localeCompare(b.type) : a.status.localeCompare(b.status)) || b.detection_timestamp.localeCompare(a.detection_timestamp)); }, [data, sort]);
  const a = analysisReady ? data?.analysis : null;
  const last = data?.candles[data.candles.length - 1];
  const decision = (a?.direction ?? 'WAIT').toUpperCase();
  const currentPattern = data?.patterns.find(p => p.id === a?.pattern_id);
  const displayPrecisionIssue = pricesCollapseAtPrecision(a, symbol.startsWith('EUR') ? 5 : 3);
  const chartData = useMemo(() => data && (!analysisReady || displayPrecisionIssue) ? {...data, analysis: null} : data, [data, analysisReady, displayPrecisionIssue]);
  const initialSetupState = setupDisplayState(a, source, currentPattern?.status);
  const setupState = displayPrecisionIssue && initialSetupState === 'CURRENT' ? 'UNVERIFIED' : initialSetupState;
  const hiddenForFocus = Boolean(focus && focus.id !== a?.pattern_id);
  const feedState = mt5Status?.status ?? 'UNVERIFIED';
  const feedCritical = needsFeedAttention(feedState, mt5SetupAvailable);
  const feedReasons = summarizeFeedReasons(mt5Status?.reasons);
  const gapClassifications = summarizeGapClassifications(mt5Status?.gaps);
  const parsedRiskBudget = parseRiskBudget(riskBudgetInput);
  const budgetMatches = appliedRiskBudget !== null && parsedRiskBudget === appliedRiskBudget;
  const currentBrokerRisk = budgetMatches && appliedRiskBudget !== null && brokerRiskMatchesSnapshot(brokerRisk, source, symbol, timeframe, data?.snapshot_sha256, mt5SetupAvailable) && brokerRisk?.requestKey === riskRequestParams(source, symbol, timeframe, settings, appliedRiskBudget) && brokerRisk?.risk_budget === appliedRiskBudget ? brokerRisk : null;
  const setupAge = barsSinceConfirmation(currentPattern?.confirmation_timestamp, data?.indicators ?? []);
  const brokerRiskRow = (label: string, value: number | null | undefined, digits = 2) => <div className="detail-row"><span>{label}</span><strong>{formatNumber(value, digits)}</strong></div>;
  const risk = a?.risk;
  const riskRow = (key: string, label: string, prefix = '', digits = 2) => <div className="detail-row"><span>{label}</span><strong>{typeof risk?.[key] === 'number' ? `${prefix}${formatNumber(risk[key], digits)}${key === 'rounded_lots' && risk[key] === 0 ? ' · below minimum' : ''}` : 'Unverified / —'}</strong></div>;
  return <div className="app-shell">
    <header className="topbar">
      <div className="brand"><div className="brand-mark"><BarChart3 size={19}/></div><div><div className="brand-name">QUANT <span>TERMINAL</span></div><div className="brand-sub">PERSONAL MARKET WORKSPACE</div></div></div>
      <div className="header-divider"/>
      <div className="header-selects"><label><span>DATA SOURCE</span><div className="select-wrap"><select value={source} onChange={e => changeSelection('source', e.target.value)} aria-label="Data source"><option value="exness">Exness Historical</option><option value="mt5">MT5 Live — Exness Demo</option><option value="massive">External Market Data</option></select><ChevronDown size={13}/></div></label><label><span>INSTRUMENT</span><div className="select-wrap"><select value={symbol} onChange={e => changeSelection('symbol', e.target.value)} aria-label="Instrument"><option value="EURUSDm">{isExternal ? 'EUR/USD' : 'EURUSDm'}</option><option value="XAUUSDm">{isExternal ? 'XAU/USD' : 'XAUUSDm'}</option></select><ChevronDown size={13}/></div></label><label><span>TIMEFRAME</span><div className="select-wrap"><select value={timeframe} onChange={e => changeSelection('timeframe', e.target.value)} aria-label="Timeframe"><option>M15</option><option>H1</option><option value="H4" disabled={isExternal}>{isExternal ? "H4 · unavailable" : "H4"}</option></select><ChevronDown size={13}/></div></label></div>
      <div className="top-right"><div className="dataset-label"><span>{isExternal ? 'LATEST ANALYZED BAR' : isMt5 ? 'LATEST COMPLETED BAR' : 'LATEST OBSERVATION'}</span><strong>{clockLabel(last?.timestamp)}</strong><small>{isExternal ? 'UTC · end-of-day feed' : 'Broker clock · timezone unverified'}</small></div><div className="offline-badge"><span className="pulse-dot"/>{isExternal ? 'EXTERNAL / END-OF-DAY' : isMt5 ? `MT5 / ${mt5Status?.status ?? 'UNVERIFIED'}` : 'HISTORICAL / OFFLINE DATA'}</div></div>
    </header>
    <main className="workspace">
      <div className="workspace-heading"><div><div className="eyebrow"><span className="accent-line"/> {isMt5 ? 'MT5 MARKET DATA' : 'HISTORICAL MARKET ANALYSIS'} <span className="eyebrow-divider">/</span> WORKSPACE 01</div><h1>Market overview <span> / {displaySymbol}</span></h1><p>Explore price action and transparent, rule-based setups.</p></div><div className="workspace-meta"><Clock3 size={14}/> {isExternal ? 'External UTC history' : 'Server-time history'} <span>·</span> <b>READ ONLY</b></div></div>
      <section className="terminal-grid">
        <div className="chart-card panel">
          <div className="chart-header"><div className="instrument"><div className="instrument-icon">{symbol.startsWith('EUR') ? '€' : 'Au'}</div><div><div className="instrument-title">{displaySymbol} <span>{timeframe}</span></div><div className="muted">{symbol.startsWith('EUR') ? 'Euro / US Dollar' : 'Gold / US Dollar'} <span className="separator">·</span> {isExternal ? 'Massive end-of-day bars' : isMt5 ? 'Exness Demo · incremental MT5 bars' : 'MT5 historical bars'}</div></div></div><div className="chart-price"><span>LATEST CLOSE</span><strong>{formatNumber(last?.close, symbol.startsWith('EUR') ? 5 : 3)}</strong></div></div>
          <div className="toolbar"><div className="toolbar-title"><Layers3 size={14}/> OVERLAYS</div><div className="toggles">{overlays.map(([key,label,color]) => <button key={key} type="button" aria-pressed={visibility[key]} className={`toggle ${visibility[key] ? 'on' : ''}`} onClick={() => setVisibility(v => ({...v, [key]: !v[key]}))}><i style={{background: color}}/>{label}</button>)}</div><label className="pattern-filter">Pattern lines<select aria-label="Pattern lines" value={patternLineMode} disabled={!visibility.patterns} onChange={e => setPatternLineMode(e.target.value as PatternLineMode)}><option value="all">All patterns</option><option value="confirmed">Currently confirmed</option></select></label><button className="icon-button refresh" onClick={() => void refresh()} disabled={refreshing} title={isExternal ? "Refresh external feed" : "Reload snapshot"} aria-label={isExternal ? "Refresh external feed" : "Reload snapshot"}><RefreshCw size={15}/></button></div>
          {isExternal && <div className="external-status" role="status"><strong>Massive · end-of-day · {readable(externalStatus?.freshness ?? 'UNKNOWN')}</strong><span>Latest observed: {clockLabel(externalStatus?.latest_observed_candle)} · Verified complete: {clockLabel(externalStatus?.latest_completed_candle)} · Last successful fetch: {timeLabel(externalStatus?.last_successful_fetch, 'utc')}</span><span>Unknown interval gaps: {externalStatus?.gap_count ?? '—'} (not classified as outages).</span><span>Massive OHLC uses its quote bid side. The latest observed candle is excluded from analysis because finality is unverified. External H4 is unavailable. External prices are not verified Exness execution quotes. {externalStatus?.error ?? ''}</span><button onClick={() => void refresh()} disabled={refreshing}>{refreshing ? 'Refreshing…' : 'Refresh'}</button></div>}
          {isMt5 && <div className={`feed-health ${feedCritical ? 'attention' : 'healthy'}`} role="status">
            <div className="feed-summary"><strong>MT5 · {readable(feedState)}</strong><span>{connectionLabel(mt5Status?.connection_status)} · {mt5Status?.history_count ?? 'unknown'} bars · {mt5Status?.current_segment_count ?? 'unknown'} contiguous · {mt5Status?.unresolved_gap_count ?? 'unknown'} unresolved gaps</span></div>
            {feedCritical && <p className="feed-critical"><strong>SETUP UNAVAILABLE · </strong>{feedReasons.length ? feedReasons.join(' · ') : 'Feed health or the matching chart snapshot is not verified.'} Current setups and trade levels are hidden until feed health and the displayed snapshot are verified.</p>}
            <details className="feed-details"><summary>Feed details</summary><div tabIndex={0} aria-label="Feed diagnostics"><span>Gap periods: {gapClassifications.join(' · ')} · Unresolved revision records: {typeof mt5Status?.unresolved_revision_count === 'number' ? mt5Status.unresolved_revision_count : 'unknown'}</span><span>Exporter heartbeat age: {typeof mt5Status?.heartbeat_age_seconds === 'number' ? `${formatNumber(mt5Status.heartbeat_age_seconds, 0)} s` : 'unknown'} · Last ingestion: {timeLabel(mt5Status?.last_ingestion_utc?.replace('+00:00', 'Z'), 'utc')}</span><span>Latest completed candle (broker clock): {timeLabel(mt5Status?.latest_completed_candle, 'broker')} · Target quote: {readable(mt5Status?.target_quote_status)}{typeof mt5Status?.target_quote_age_seconds === 'number' ? ` (${formatNumber(mt5Status.target_quote_age_seconds, 0)} s)` : ''}</span><span>MT5-reported Exness Demo identity is not independently authenticated. History continuity with the offline snapshot is unverified; no sources are combined. {mt5Status?.reasons?.join(' · ') ?? 'Waiting for bridge health.'}</span></div></details>
          </div>}
          {error && data && <div className="external-status" role="alert">Latest request failed; showing last valid data. {error}</div>}
          <div className="chart-body">{loading && !data ? <div className="chart-state"><RefreshCw className="spin" size={23}/><strong>Loading historical snapshot</strong><span>Checking data and preparing your chart…</span></div> : error && !data ? <div className="chart-state error"><ShieldAlert size={25}/><strong>Unable to load data</strong><span>{error}</span><button onClick={() => setReload(n => n + 1)}>Try again</button></div> : data && data.candles.length ? <Chart data={chartData!} visibility={visibility} focus={focus} setupState={setupState} patternLineMode={patternLineMode}/> : <div className="chart-state"><strong>No historical candles available</strong><span>Check the selected dataset and backend.</span></div>}</div>
          <div className="chart-footer"><div><span className="footer-dot"/> {isExternal ? 'EXTERNAL SNAPSHOT' : isMt5 ? 'MT5 MUTABLE CACHE' : 'IMMUTABLE SILVER SNAPSHOT'} <span className="hash">{data?.snapshot_sha256.slice(0, 12) ?? '—'}</span><br/>Latest candle open: {clockLabel(last?.timestamp)} {isExternal ? 'UTC' : '(broker clock, timezone unverified)'}</div><span>Drag to pan <span className="separator">·</span> Scroll to zoom <span className="separator">·</span> {isExternal ? 'UTC labels' : 'Broker-clock labels'} <span className="separator">·</span> Lines show the latest setup only; selecting another pattern hides them</span></div>
        </div>
        <aside className="analysis-card panel"><div className="aside-heading"><div><div className="eyebrow">RESEARCH WORKSPACE</div><h2>Decision support</h2></div><div className="aside-icon"><Crosshair size={17}/></div></div>
          <div className="decision-block"><div className="section-label">ANALYTICAL DIRECTION <CircleHelp size={13}/></div><div className={`decision ${decision === 'BUY' ? 'buy' : decision === 'SELL' ? 'sell' : 'wait'}`}>{decision === 'BUY' ? <ArrowUpRight/> : decision === 'SELL' ? <ArrowDownRight/> : <Activity/>}<span>{decision}</span><small>{isExternal ? 'End-of-day analysis only' : isMt5 ? (mt5SetupAvailable ? 'Analytical only · no orders' : 'Feed not ready · WAIT') : 'Historical analysis only'}</small></div><div className="eligibility"><ShieldAlert size={15}/><div><b>OVERALL ACTION: {a?.overall_action ?? 'WAIT'}</b><span>{readable(a?.execution_eligibility ?? 'BLOCKED_UNVERIFIED')}</span></div></div></div>
          <div className="aside-section"><div className="section-label">MARKET CONTEXT <span>14 PERIODS</span></div><div className="metrics-grid"><Metric label="EMA 20" value={formatNumber(a?.ema20, symbol.startsWith('EUR') ? 5 : 3)} accent="#e5bb69"/><Metric label="EMA 50" value={formatNumber(a?.ema50, symbol.startsWith('EUR') ? 5 : 3)} accent="#9a94f7"/><Metric label="ATR 14" value={formatNumber(a?.atr14, symbol.startsWith('EUR') ? 5 : 3)}/><Metric label="ADX 14" value={formatNumber(a?.adx14, 2)}/></div><div className="detail-row trend"><span>Trend classification</span><strong>{readable(a?.trend)}</strong></div><p className="setup-focus">{!a ? 'Waiting for a matching, validated analysis.' : a.trend === 'BULLISH' ? 'EMA 20 is above EMA 50 in the latest analyzed candle.' : a.trend === 'BEARISH' ? 'EMA 20 is below EMA 50 in the latest analyzed candle.' : a.trend === 'NEUTRAL' ? 'EMA 20 and EMA 50 are equal; market trend is neutral.' : 'Indicators are still unavailable or warming up.'} {a?.pattern_status === 'CONFIRMED' ? 'A confirmed pattern is present.' : a ? 'No confirmed current pattern is available.' : ''}</p></div>
          <div className="aside-section"><div className="section-label">PATTERN &amp; SETUP <span>NOT AN ORDER</span></div><div className="detail-row"><span>Latest close boundary</span><strong>{clockLabel(data?.indicators[data.indicators.length - 1]?.available_at_timestamp)}</strong></div><div className="detail-row"><span>Detected pattern</span><strong>{readable(currentPattern?.type)}</strong></div><div className="detail-row"><span>Pattern detection</span><strong>{clockLabel(currentPattern?.detection_timestamp)}</strong></div><div className="detail-row"><span>Pattern confirmation</span><strong>{clockLabel(currentPattern?.confirmation_timestamp)}</strong></div><div className="detail-row"><span>Pattern status</span><strong>{readable(a?.pattern_status)}</strong></div>{a?.entry != null && <><div className="detail-row"><span>Reference as of candle close</span><strong>{clockLabel(data?.indicators[data.indicators.length - 1]?.available_at_timestamp)}</strong></div><div className="detail-row"><span>Bars since confirmation</span><strong>{setupAge ?? 'Age unavailable'}</strong></div><p className="setup-focus">No age-based expiry is applied; inspect the confirmation time and price before using a reference.</p></>}<div className={`setup-classification ${setupState.toLowerCase()}`}>{setupDisplayLabel(setupState, source)}</div>{displayPrecisionIssue && <p className="setup-focus" role="status">Entry, stop or target round to the same displayed price. These references are unverified; broker tick size and execution precision are not established.</p>}{a?.entry != null && <p className="setup-focus">Reference levels are recalculated from the displayed snapshot: entry uses the pattern neckline, while stop and target use the latest ATR. They may change and are not recorded execution levels.</p>}{hiddenForFocus && <p className="setup-focus">Selected {readable(focus?.status)} pattern differs from the latest setup; latest setup lines are hidden. Select the row again to clear focus.</p>}<div className="detail-row"><span>Proposed entry</span><strong className={setupState === 'CURRENT' ? 'text-green' : 'text-reference'}>{formatNumber(a?.entry, symbol.startsWith('EUR') ? 5 : 3)}</strong></div><div className="detail-row"><span>Stop loss</span><strong className={setupState === 'CURRENT' ? 'text-red' : 'text-reference'}>{formatNumber(a?.stop_loss, symbol.startsWith('EUR') ? 5 : 3)}</strong></div><div className="detail-row"><span>Take profit</span><strong className={setupState === 'CURRENT' ? 'text-blue' : 'text-reference'}>{formatNumber(a?.take_profit, symbol.startsWith('EUR') ? 5 : 3)}</strong></div><div className="detail-row"><span>Trigger reached (latest close)</span><strong>{a?.trigger_reached == null ? "—" : a.trigger_reached ? "Yes · not executed" : "No · not executed"}</strong></div><div className="detail-row"><span>Latest close vs target</span><strong className={a?.target_reference_status === "AT_OR_BEYOND" ? "text-amber" : ""}>{a?.target_reference_status === "AT_OR_BEYOND" ? "At / beyond · stale reference" : a?.target_reference_status === "NOT_AT_OR_BEYOND" ? "Not at / beyond" : "—"}</strong></div><div className="detail-row"><span>Risk / reward</span><strong>{typeof a?.risk_reward === 'number' ? `1 : ${formatNumber(a.risk_reward, 2)}` : '—'}</strong></div>{riskRow('entry_stop_distance', 'Entry-to-stop distance', '', symbol.startsWith('EUR') ? 5 : 3)}{riskRow('theoretical_lots', 'Theoretical lot size', '', 6)}{riskRow('rounded_lots', 'Rounded lot size')}{riskRow('estimated_risk_usd', 'Estimated account risk', '$')}{riskRow('estimated_trading_costs', 'Estimated trading costs', '$')}<div className="detail-row"><span>Risk check</span><strong>{readable(risk?.risk_check)}</strong></div></div>
          {isMt5 && <div className="aside-section" aria-label="Broker risk">
            <div className="section-label">BROKER RISK — UNVERIFIED <span>RESEARCH ONLY</span></div>
            <p>READ-ONLY / NO EXECUTION · Research estimates only · not executable. No order, margin or broker terms are verified.</p>
            <form className="risk-budget-form" onSubmit={e => { e.preventDefault(); const amount = parseRiskBudget(riskBudgetInput); if (amount !== null) setAppliedRiskBudget(amount); }}>
              <label htmlFor="risk-budget">Illustrative risk budget (USD)</label>
              <div><input id="risk-budget" type="number" inputMode="decimal" min="0" max="1000000" step="any" required value={riskBudgetInput} onChange={e => setRiskBudgetInput(e.target.value)} placeholder="Enter amount" aria-describedby="risk-budget-help"/><button type="submit" disabled={parsedRiskBudget === null}>Apply budget</button></div>
              <p id="risk-budget-help">Your input is illustrative; it does not verify account funds, position size or execution.</p>
            </form>
            <div className="detail-row"><span>Specification source</span><strong>{brokerSpecification?.instrument === symbol && brokerSpecification?.specification_status === 'OBSERVED_UNAUTHENTICATED' ? 'MT5 Snapshot Observed — Source Not Fully Verified' : 'Unavailable / unverified'}</strong></div>
            <div className="detail-row"><span>Broker observation (timezone unknown)</span><strong>{specValue('broker_observed_at')}</strong></div>
            <div className="detail-row"><span>Contract size / tick size</span><strong>{specValue('contract_size')} / {specValue('tick_size')}</strong></div>
            <div className="detail-row"><span>Volume min / max / step</span><strong>{specValue('volume_min')} / {specValue('volume_max')} / {specValue('volume_step')}</strong></div>
            <div className="detail-row"><span>Native comparison / freshness</span><strong>{nativeComparison?.instrument === symbol && nativeComparison.comparisons.length ? 'OBSERVED · UNVERIFIED' : 'UNAVAILABLE · UNVERIFIED'} / UNKNOWN</strong></div>
            {nativeComparison?.instrument === symbol && nativeComparison.comparisons.map((item, index) => <div className="detail-row" key={`native-${index}`}><span>{item.direction} {item.case} absolute difference</span><strong>{item.comparison?.absolute_difference ?? '—'}</strong></div>)}
            {brokerSpecification?.instrument === symbol && brokerSpecification?.assessment?.problems?.length ? <p>Specification issues: {brokerSpecification.assessment.problems.join(' · ')}</p> : null}
            {!currentBrokerRisk ? <p>{!budgetMatches ? 'Enter and apply an illustrative USD budget to review risk.' : brokerRiskError ? 'Broker risk information is unavailable.' : 'Waiting for a matching, healthy MT5 snapshot.'}</p> : <>
              <div className="detail-row"><span>Instrument / broker source</span><strong>{currentBrokerRisk.instrument} · {readable(currentBrokerRisk.broker_source)}</strong></div>
              <div className="detail-row"><span>Account / specification</span><strong>{readable(currentBrokerRisk.account_type)} · {readable(currentBrokerRisk.specification_status)}</strong></div>
              <div className="detail-row"><span>Specification observation</span><strong>{timeLabel(currentBrokerRisk.specification_snapshot_time, 'utc')}</strong></div>
              <div className="detail-row"><span>Feed / setup status</span><strong>{readable(currentBrokerRisk.feed_quality_status)} · {readable(currentBrokerRisk.setup_status)}</strong></div>
              {brokerRiskRow('Price-distance reward / risk (ratio)', currentBrokerRisk.price_distance_reward_risk)}
              {brokerRiskRow('Gross monetary reward / risk (ratio)', currentBrokerRisk.gross_risk_reward)}
              {brokerRiskRow('Illustrative risk budget (USD)', currentBrokerRisk.risk_budget)}
              {brokerRiskRow('Theoretical volume (lots)', currentBrokerRisk.theoretical_volume, 6)}
              {brokerRiskRow('Normalized volume (lots)', currentBrokerRisk.normalized_volume, 6)}
              {brokerRiskRow('Expected gross loss', currentBrokerRisk.expected_gross_loss)}
              {brokerRiskRow('Expected gross profit', currentBrokerRisk.expected_gross_profit)}
              {brokerRiskRow('Margin estimate', currentBrokerRisk.margin_estimate)}
              <div className="detail-row"><span>Commission</span><strong>{formatNumber(currentBrokerRisk.known_costs?.commission)}</strong></div>
              <div className="detail-row"><span>Spread cost</span><strong>{formatNumber(currentBrokerRisk.known_costs?.spread)}</strong></div>
              <div className="detail-row"><span>Slippage cost</span><strong>{formatNumber(currentBrokerRisk.known_costs?.slippage)}</strong></div>
              <div className="detail-row"><span>Financing</span><strong>{formatNumber(currentBrokerRisk.known_costs?.financing)}</strong></div>
              <p>Unavailable costs are not zero. Gross figures exclude unverified costs.</p>
              {(currentBrokerRisk.blocking_reasons ?? []).map((reason, index) => <p key={`block-${index}`}>{reason}</p>)}
              {(currentBrokerRisk.warnings ?? []).map((warning, index) => <p key={`warning-${index}`}>{warning}</p>)}
            </>}
          </div>}
          <details className="settings"><summary><SlidersHorizontal size={13}/> Analysis settings</summary><form onSubmit={e => {e.preventDefault(); setData(null); setFocus(null); setSettings({...draft});}}><div className="settings-grid">{ANALYSIS_SETTING_FIELDS.map(([key,label,min,max,step]) => <label key={key}>{label}<input type="number" min={min} max={max} step={step} required value={draft[key]} onChange={e => setDraft(d => ({...d,[key]: Number(e.target.value)}))}/></label>)}</div><button type="submit">Apply settings</button></form></details>
          <div className="warning-box"><ShieldAlert size={16}/><div><strong>Execution is not verified</strong><p>{isMt5 && !mt5SetupAvailable ? `MT5 feed is not verified for current analysis. ${(mt5Status?.reasons ?? []).join(' · ')}` : a?.blocking_reasons?.length ? a.blocking_reasons.join(' · ') : 'Broker specifications, quote availability and historical timing are not verified.'}</p></div></div>
        </aside>
      </section>
      <section className="patterns-card panel"><div className="pattern-header"><div><div className="eyebrow">PRICE STRUCTURE</div><h2>Recent patterns <span>{patterns.length}</span></h2><p>Pivots and anchors are retrospective: known only after confirmation. Pattern status is as of the latest candle. Only patterns with both anchors in the displayed chart are listed.</p></div><div className="table-controls"><SlidersHorizontal size={14}/><label htmlFor="pattern-sort">Sort by</label><select id="pattern-sort" value={sort} onChange={e => setSort(e.target.value as typeof sort)}><option value="recent">Most recent</option><option value="type">Pattern type</option><option value="status">Status</option></select><ChevronDown size={13}/></div></div>
        <div className="table-wrap"><table><thead><tr><th>PATTERN</th><th>STATUS</th><th>DETECTED · {isExternal ? 'UTC' : 'BROKER CLOCK'}</th><th>CONFIRMED · {isExternal ? 'UTC' : 'BROKER CLOCK'}</th><th>NECKLINE</th><th></th></tr></thead><tbody>{patterns.length ? patterns.slice(0, 30).map(pattern => <tr key={pattern.id} onClick={() => setFocus(previous => previous?.id === pattern.id ? null : pattern)} tabIndex={0} onKeyDown={e => {if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setFocus(previous => previous?.id === pattern.id ? null : pattern); }}}><td><span className={`pattern-icon ${pattern.type === 'DOUBLE_TOP' ? 'bear' : 'bull'}`}>{pattern.type === 'DOUBLE_TOP' ? <ArrowDownRight size={14}/> : <ArrowUpRight size={14}/>}</span><strong>{readable(pattern.type)}</strong></td><td><span className={`status-tag ${pattern.status.toLowerCase()}`}>{readable(pattern.status)}</span>{pattern.tracking_ended_reason && <span className="tracking-note"> Tracking ended: {readable(pattern.tracking_ended_reason)}</span>}</td><td>{clockLabel(pattern.detection_timestamp)}</td><td>{clockLabel(pattern.confirmation_timestamp)}</td><td>{formatNumber(pattern.neckline, symbol.startsWith('EUR') ? 5 : 3)}</td><td className="row-action">VIEW ON CHART ↗</td></tr>) : <tr><td colSpan={6} className="empty-row">{loading ? 'Looking for historical patterns…' : error ? 'Pattern data is unavailable.' : 'No patterns detected in this window.'}</td></tr>}</tbody></table></div>
      </section>
      <footer><span><i/> HISTORICAL RESEARCH ENVIRONMENT</span><span>Decision support only <b>·</b> No broker execution <b>·</b> Not investment advice</span></footer>
    </main>
  </div>;
}

const appContainer = document.getElementById('root');
if (!appContainer) throw new Error('Application root element is missing.');
const appRoot = getOrCreateAppRoot(appContainer as HTMLElement & {__quantTerminalRoot?: Root}, () => createRoot(appContainer));
appRoot.render(<React.StrictMode><App/></React.StrictMode>);
