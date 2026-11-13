import type { UTCTimestamp } from 'lightweight-charts';
import type { Analysis } from './types';
// Chart library requires an epoch. Encode the displayed broker-clock components as UTC
// only as a plotting coordinate; this is not a claim about the broker's timezone.
export function chartTime(timestamp: string, basis: 'broker' | 'utc' = 'broker'): UTCTimestamp {
  if (basis === 'utc') {
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/.test(timestamp)) throw new Error(`Invalid UTC timestamp: ${timestamp}`);
    const coordinate = Date.parse(timestamp);
    if (!Number.isFinite(coordinate) || new Date(coordinate).toISOString().slice(0, 19) !== timestamp.slice(0, 19)) throw new Error(`Invalid UTC timestamp: ${timestamp}`);
    return (coordinate / 1000) as UTCTimestamp;
  }
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(timestamp)) throw new Error(`Invalid broker-clock timestamp: ${timestamp}`);
  const coordinate = Date.parse(timestamp + 'Z');
  if (!Number.isFinite(coordinate) || new Date(coordinate).toISOString().slice(0, 19) !== timestamp.slice(0, 19)) throw new Error(`Invalid broker-clock timestamp: ${timestamp}`);
  return (coordinate / 1000) as UTCTimestamp;
}
export function brokerLabel(timestamp: string | null | undefined): string {
  return timestamp ? timestamp.replace('T', ' ').replace(/\.\d+$/, '') : '—';
}
export function timeLabel(timestamp: string | null | undefined, basis: 'broker' | 'utc'): string {
  if (!timestamp) return '—';
  if (basis === 'broker') return brokerLabel(timestamp);
  return timestamp.replace('T', ' ').replace(/\.\d+Z$/, 'Z').replace(/Z$/, ' UTC');
}
export function formatNumber(value: unknown, digits = 5): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—';
}
export function readable(value: unknown): string {
  return typeof value === 'string' && value ? value.replace(/_/g, ' ') : 'Unavailable';
}

/** Reuse one React root on the same DOM container across Vite module replacements. */
export function getOrCreateAppRoot<T>(container: {__quantTerminalRoot?: T}, create: () => T): T {
  if (container.__quantTerminalRoot === undefined) container.__quantTerminalRoot = create();
  return container.__quantTerminalRoot;
}

/** Form constraints shared with tests. Decimal inputs are not limited to an arbitrary step grid. */
export const DEFAULT_ANALYSIS_SETTINGS = { left: 3, right: 3, tolerance_atr: 0.5, min_touches: 2, min_separation: 3, buffer_atr: 0.1, risk_reward: 2 };
export const ANALYSIS_SETTING_FIELDS = [
  ['left', 'Left bars', 1, 20, 1],
  ['right', 'Right bars', 1, 20, 1],
  ['tolerance_atr', 'Tolerance (ATR)', 0.01, 5, 'any'],
  ['min_touches', 'Zone touches', 2, 20, 1],
  ['min_separation', 'Min. separation', 1, 500, 1],
  ['buffer_atr', 'Stop buffer (ATR)', 0.01, 5, 'any'],
  ['risk_reward', 'Target R:R', 0.01, 10, 'any'],
] as const;

/** Every data request carries its explicit source; symbols are resolved by the API. */
export function terminalParams(source: 'exness' | 'massive' | 'mt5', symbol: string, timeframe: string, settings: Record<string, number>): string {
  return new URLSearchParams({ symbol, timeframe, source, limit: '800', ...Object.fromEntries(Object.entries(settings).map(([key, value]) => [key, String(value)])) }).toString();
}

/** Reject responses from another market, timeframe, source, snapshot or analysis configuration. */
export function snapshotResponsesMatch(
  bars: {source?: unknown; symbol?: unknown; timeframe?: unknown; snapshot_sha256?: unknown},
  analyses: ReadonlyArray<{source?: unknown; symbol?: unknown; timeframe?: unknown; snapshot_sha256?: unknown; analysis_config?: unknown}>,
  selection: {source: string; symbol: string; timeframe: string; settings: Record<string, number>},
): boolean {
  if (typeof bars.snapshot_sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(bars.snapshot_sha256)) return false;
  const identityMatches = (value: typeof bars) => value.source === selection.source && value.symbol === selection.symbol && value.timeframe === selection.timeframe && value.snapshot_sha256 === bars.snapshot_sha256;
  return identityMatches(bars) && analyses.length === 3 && analyses.every(value => {
    const config = value.analysis_config;
    return identityMatches(value) && typeof config === 'object' && config !== null &&
      Object.entries(selection.settings).every(([key, expected]) => (config as Record<string, unknown>)[key] === expected);
  });
}

/** Check display rounding only; actual broker tick size and order validity remain unverified. */
export function pricesCollapseAtPrecision(analysis: Analysis | null | undefined, digits: number): boolean {
  if (!Number.isInteger(digits) || digits < 0 || digits > 100 || !analysis) return false;
  const values = [analysis.entry, analysis.stop_loss, analysis.take_profit];
  if (!values.every((value): value is number => typeof value === 'number' && Number.isFinite(value))) return false;
  return new Set(values.map(value => value.toFixed(digits))).size !== values.length;
}

/** Old gaps are disclosed; the current indicator segment must be contiguous and warm. */
export function mt5CanShowSetup(health: {status?: string; unresolved_gap_count?: number | null; unresolved_revision_count?: number | null; history_count?: number | null; current_segment_count?: number | null; snapshot_sha256?: string | null} | null, displayedSnapshot: string | null | undefined, loading = false, requestFailed = false): boolean {
  return !loading && !requestFailed && health?.status === 'LIVE' && typeof health.unresolved_gap_count === 'number' && Number.isSafeInteger(health.unresolved_gap_count) && health.unresolved_gap_count >= 0 && health.unresolved_revision_count === 0 && typeof health.history_count === 'number' && Number.isSafeInteger(health.history_count) && typeof health.current_segment_count === 'number' && Number.isSafeInteger(health.current_segment_count) && health.current_segment_count >= 50 && health.current_segment_count <= health.history_count && typeof health.snapshot_sha256 === 'string' && /^[0-9a-f]{64}$/.test(health.snapshot_sha256) && health.snapshot_sha256 === displayedSnapshot;
}

/** Ignore absent/unchanged identities to avoid reloading the full chart each poll. */
export function snapshotChanged(previous: string | null, next: string | null | undefined): boolean {
  return typeof next === 'string' && next.length > 0 && next !== previous;
}

/** User-entered illustrative USD budget; no account equity or broker status is inferred. */
export function parseRiskBudget(input: string): number | null {
  if (!input.trim()) return null;
  const amount = Number(input);
  return Number.isFinite(amount) && amount > 0 && amount <= 1_000_000 ? amount : null;
}

/** Identify the exact budget and analysis settings associated with an async risk result. */
export function riskRequestParams(source: 'exness' | 'massive' | 'mt5', symbol: string, timeframe: string, settings: Record<string, number>, budget: number): string {
  const params = new URLSearchParams(terminalParams(source, symbol, timeframe, settings));
  params.set('risk_budget_usd', String(budget));
  return params.toString();
}

/** Count supplied completed candles since confirmation; null means the origin is outside the analysis window. */
export function barsSinceConfirmation(confirmation: string | null | undefined, indicators: ReadonlyArray<{available_at_timestamp: string}>): number | null {
  if (!confirmation) return null;
  const index = indicators.findIndex(row => row.available_at_timestamp === confirmation);
  return index < 0 ? null : indicators.length - index - 1;
}

export const MT5_POLL_INTERVAL_MS = 8000;
export const MT5_REQUEST_TIMEOUT_MS = 6000;


/** Presentation classification only; it never changes the analysis or trade eligibility. */
export type SetupDisplayState = 'NONE' | 'CURRENT' | 'HISTORICAL' | 'STALE' | 'INVALIDATED' | 'UNVERIFIED';
export function setupDisplayState(analysis: Analysis | null | undefined, source: 'exness' | 'massive' | 'mt5', patternStatus?: string | null): SetupDisplayState {
  if (!analysis || ![analysis.entry, analysis.stop_loss, analysis.take_profit].every(value => typeof value === 'number' && Number.isFinite(value))) return 'NONE';
  if (analysis.pattern_status === 'INVALIDATED' || patternStatus === 'INVALIDATED') return 'INVALIDATED';
  if (analysis.target_reference_status === 'AT_OR_BEYOND') return 'STALE';
  if (source !== 'mt5') return 'HISTORICAL';
  if (analysis.pattern_status !== 'CONFIRMED' || analysis.target_reference_status !== 'NOT_AT_OR_BEYOND') return 'UNVERIFIED';
  return 'CURRENT';
}
export function setupDisplayLabel(state: SetupDisplayState, source: 'exness' | 'massive' | 'mt5'): string {
  const labels: Record<SetupDisplayState, string> = {
    NONE: 'No current setup available.', CURRENT: 'Active analytical reference · no age expiry · not executable',
    HISTORICAL: 'Historical setup · not executable', STALE: 'Stale reference levels · not executable',
    INVALIDATED: 'Invalidated levels · not executable', UNVERIFIED: 'Unverified reference levels · not executable',
  };
  return state === 'STALE' && source !== 'mt5' ? 'Historical stale reference levels · not executable' : labels[state];
}
/** A selected different pattern is only chart focus; never imply latest levels belong to it. */
export function showSetupLevels(state: SetupDisplayState, analysisPatternId: string | null | undefined, focusedPatternId: string | null | undefined): boolean {
  return state !== 'NONE' && (!focusedPatternId || focusedPatternId === analysisPatternId);
}

/** Non-live or snapshot-ineligible states must stay visible when diagnostics are collapsed. */
export function needsFeedAttention(status: string | null | undefined, setupAvailable: boolean): boolean {
  return status !== 'LIVE' || !setupAvailable;
}

/** Distinguish connection evidence from the overall feed-health classification. */
export function connectionLabel(value: unknown): string {
  if (value === 'CONNECTED') return 'Connected';
  if (value === 'DISCONNECTED') return 'Disconnected';
  return 'Connection unknown';
}


/** Keep actionable conditions visible without repeating full revision identifiers. */
export function summarizeFeedReasons(reasons: readonly string[] | null | undefined): string[] {
  const result = new Set<string>();
  for (const reason of reasons ?? []) {
    if (typeof reason !== 'string' || !reason.trim()) continue;
    const concise = reason.startsWith('conflicting duplicate candle at ') || /^\d+ candle revision\(s\) remain unresolved in the persistent ledger\.$/.test(reason)
      ? 'Unresolved candle revision; see Feed details.'
      : reason;
    result.add(concise);
  }
  return Array.from(result);
}

/** Presentation-only chart filter; the source patterns and their statuses are unchanged. */
export type PatternLineMode = 'all' | 'confirmed';
export function selectChartPatterns<T extends {status: string}>(patterns: readonly T[], mode: PatternLineMode): T[] {
  return mode === 'confirmed' ? patterns.filter(pattern => pattern.status === 'CONFIRMED') : Array.from(patterns);
}

/** Only display a classification actually supplied by the data source. */
export function summarizeGapClassifications(gaps: readonly {classification?: string | null}[] | null | undefined): string[] {
  if (!Array.isArray(gaps)) return ['Gap classifications unavailable.'];
  if (!gaps.length) return ['No gap periods recorded.'];
  const labels: Record<string, string> = {
    VERIFIED_SESSION_CLOSURE: 'Verified closure',
    VERIFIED_BROKER_NO_BAR: 'Verified broker no-bar',
    RECOVERABLE_HISTORY_GAP: 'Recoverable history gap',
    SOURCE_DATA_CONFLICT: 'Source data conflict',
    UNKNOWN_SESSION_OR_MISSING: 'Unknown session/missing-data gap',
    UNKNOWN: 'Unknown session/missing-data gap',
  };
  const counts = new Map<string, number>();
  for (const gap of gaps) {
    const key = gap && typeof gap.classification === 'string' ? gap.classification : '';
    const label = Object.prototype.hasOwnProperty.call(labels, key) ? labels[key] : 'Unclassified gap';
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return Array.from(counts, ([label, count]) => `${label}: ${count}`);
}


/** Broker risk is displayable only for the currently verified MT5 chart snapshot. */
export function brokerRiskMatchesSnapshot(
  risk: {instrument?: string; timeframe?: string; snapshot_sha256?: string | null} | null,
  source: string, symbol: string, timeframe: string, displayedSnapshot: string | null | undefined,
  feedReady: boolean,
): boolean {
  return source === 'mt5' && feedReady && Boolean(displayedSnapshot) &&
    risk !== null && risk.instrument === symbol && risk.timeframe === timeframe &&
    risk.snapshot_sha256 === displayedSnapshot;
}
