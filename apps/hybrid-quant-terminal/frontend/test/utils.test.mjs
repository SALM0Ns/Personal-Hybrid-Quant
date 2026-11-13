import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';

const source = await readFile(new URL('../src/utils.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } });
const { chartTime, brokerLabel, timeLabel, formatNumber, getOrCreateAppRoot, DEFAULT_ANALYSIS_SETTINGS, ANALYSIS_SETTING_FIELDS, terminalParams, snapshotResponsesMatch, pricesCollapseAtPrecision, mt5CanShowSetup, snapshotChanged, setupDisplayState, setupDisplayLabel, showSetupLevels, needsFeedAttention, connectionLabel, summarizeFeedReasons, selectChartPatterns, summarizeGapClassifications, brokerRiskMatchesSnapshot, parseRiskBudget, riskRequestParams, barsSinceConfirmation, MT5_POLL_INTERVAL_MS, MT5_REQUEST_TIMEOUT_MS } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);

test('broker timestamps are rendered as entered without timezone conversion or UTC claim', () => {
  assert.equal(brokerLabel('2026-10-20T13:15:00'), '2026-10-20 13:15:00');
  assert.equal(brokerLabel(null), '—');
  assert.equal(chartTime('2026-10-20T13:15:00'), Date.UTC(2026, 9, 20, 13, 15) / 1000);
});
test('plotting rejects timezone-bearing or malformed broker timestamps', () => {
  for (const timestamp of ['2026-10-20T13:15:00Z', '2026-10-20T13:15:00+02:00', 'not-a-time', '2026-02-30T13:15:00', '2026-99-20T13:15:00']) {
    assert.throws(() => chartTime(timestamp), /Invalid broker-clock timestamp/);
  }
});
test('unavailable and non-finite metric values are never presented as zero', () => {
  assert.equal(formatNumber(null), '—');
  assert.equal(formatNumber(NaN), '—');
  assert.equal(formatNumber(Infinity), '—');
  assert.equal(formatNumber(1.23456, 3), '1.235');
});


test('external UTC candles preserve UTC identity and never claim broker time', () => {
  assert.equal(chartTime('2026-10-20T13:15:00Z', 'utc'), Date.UTC(2026, 9, 20, 13, 15) / 1000);
  assert.equal(timeLabel('2026-10-20T13:15:00Z', 'utc'), '2026-10-20 13:15:00 UTC');
  assert.equal(timeLabel('2026-10-20T13:15:00', 'broker'), '2026-10-20 13:15:00');
  for (const timestamp of ['2026-10-20T13:15:00', '2026-10-20T13:15:00+02:00', '2026-02-30T13:15:00Z']) {
    assert.throws(() => chartTime(timestamp, 'utc'), /Invalid UTC timestamp/);
  }
});


test('source switching keeps historical and external requests isolated', () => {
  const a = new URLSearchParams(terminalParams('exness', 'EURUSDm', 'H1', {left: 3}));
  const b = new URLSearchParams(terminalParams('massive', 'XAUUSDm', 'M15', {left: 5}));
  assert.equal(a.get('source'), 'exness'); assert.equal(a.get('symbol'), 'EURUSDm');
  assert.equal(b.get('source'), 'massive'); assert.equal(b.get('symbol'), 'XAUUSDm');
  assert.equal(b.get('timeframe'), 'M15'); assert.equal(b.get('left'), '5');
});


test('MT5 source uses a distinct broker-clock request and does not merge sources', () => {
  const mt5 = new URLSearchParams(terminalParams('mt5', 'EURUSDm', 'H4', {left: 3}));
  assert.equal(mt5.get('source'), 'mt5');
  assert.equal(mt5.get('symbol'), 'EURUSDm');
  assert.equal(mt5.get('timeframe'), 'H4');
  assert.equal(chartTime('2026-10-20T13:15:00', 'broker'), Date.UTC(2026, 9, 20, 13, 15) / 1000);
});

test('MT5 stale, offline, unknown or insufficient contiguous health blocks current setups', () => {
  const snapshot = 'a'.repeat(64);
  const healthy = {status: 'LIVE', unresolved_gap_count: 0, unresolved_revision_count: 0, history_count: 50, current_segment_count: 50, snapshot_sha256: snapshot};
  assert.equal(mt5CanShowSetup(healthy, snapshot), true);
  for (const status of ['STALE', 'OFFLINE', 'UNVERIFIED', 'MARKET_CLOSED', 'UNKNOWN']) {
    assert.equal(mt5CanShowSetup({...healthy, status}, snapshot), false);
  }
  assert.equal(mt5CanShowSetup({...healthy, unresolved_gap_count: 1}, snapshot), true);
  assert.equal(mt5CanShowSetup({...healthy, unresolved_revision_count: 1}, snapshot), false);
  assert.equal(mt5CanShowSetup({...healthy, unresolved_revision_count: null}, snapshot), false);
  assert.equal(mt5CanShowSetup({...healthy, unresolved_revision_count: undefined}, snapshot), false);
  assert.equal(mt5CanShowSetup({...healthy, unresolved_gap_count: -1}, snapshot), false);
  assert.equal(mt5CanShowSetup({...healthy, unresolved_gap_count: null}, snapshot), false);
  assert.equal(mt5CanShowSetup({...healthy, history_count: 49}, snapshot), false);
  assert.equal(mt5CanShowSetup({...healthy, current_segment_count: 49}, snapshot), false);
  assert.equal(mt5CanShowSetup({...healthy, current_segment_count: null}, snapshot), false);
  assert.equal(mt5CanShowSetup({...healthy, current_segment_count: 51}, snapshot), false);
  assert.equal(mt5CanShowSetup(null, snapshot), false);
  assert.equal(mt5CanShowSetup(healthy, 'b'.repeat(64)), false);
  assert.equal(mt5CanShowSetup(healthy, null), false);
  assert.equal(mt5CanShowSetup(healthy, snapshot, true, false), false);
  assert.equal(mt5CanShowSetup(healthy, snapshot, false, true), false);
  assert.equal(mt5CanShowSetup({...healthy, snapshot_sha256: 'bad'}, 'bad'), false);
  assert.equal(mt5CanShowSetup({...healthy, history_count: Infinity}, snapshot), false);
});

test('MT5 polls on a bounded interval and reloads chart only for a new snapshot', () => {
  assert.equal(MT5_POLL_INTERVAL_MS, 8000);
  assert.equal(MT5_REQUEST_TIMEOUT_MS, 6000);
  assert.equal(snapshotChanged(null, null), false);
  assert.equal(snapshotChanged('a', ''), false);
  assert.equal(snapshotChanged('a', 'a'), false);
  assert.equal(snapshotChanged('a', 'b'), true);
  assert.equal(snapshotChanged(null, 'b'), true);
});


test('compact health exposes non-live and snapshot-ineligible conditions', () => {
  assert.equal(needsFeedAttention('LIVE', true), false);
  for (const status of ['UNVERIFIED', 'BLOCKED', 'STALE', 'OFFLINE', 'MARKET_CLOSED', null, undefined]) {
    assert.equal(needsFeedAttention(status, false), true);
    assert.equal(needsFeedAttention(status, true), true);
  }
  assert.equal(needsFeedAttention('LIVE', false), true);
});

test('levels are categorized without changing numerical inputs or implying execution', () => {
  const valid = {entry: 10, stop_loss: 9, take_profit: 12, pattern_status: 'CONFIRMED', target_reference_status: 'NOT_AT_OR_BEYOND'};
  assert.equal(setupDisplayState(valid, 'mt5'), 'CURRENT');
  assert.equal(setupDisplayState(valid, 'exness'), 'HISTORICAL');
  assert.equal(setupDisplayState(valid, 'massive'), 'HISTORICAL');
  assert.equal(setupDisplayState({...valid, target_reference_status:'AT_OR_BEYOND'}, 'mt5'), 'STALE');
  assert.equal(setupDisplayState({...valid, target_reference_status:'AT_OR_BEYOND'}, 'exness'), 'STALE');
  assert.equal(setupDisplayState({...valid, pattern_status:'INVALIDATED', target_reference_status:'AT_OR_BEYOND'}, 'mt5'), 'INVALIDATED');
  assert.equal(setupDisplayState(valid, 'mt5', 'INVALIDATED'), 'INVALIDATED');
  assert.equal(setupDisplayState({...valid, target_reference_status:'UNKNOWN'}, 'mt5'), 'UNVERIFIED');
  assert.equal(setupDisplayState({...valid, pattern_status:null}, 'mt5'), 'UNVERIFIED');
  assert.equal(setupDisplayState({...valid, entry:Infinity}, 'mt5'), 'NONE');
  assert.equal(setupDisplayState({...valid, stop_loss:null}, 'mt5'), 'NONE');
  assert.equal(setupDisplayState(null, 'mt5'), 'NONE');
  assert.match(setupDisplayLabel('STALE', 'exness'), /Historical.*stale.*not executable/i);
  for (const state of ['CURRENT', 'HISTORICAL', 'STALE', 'INVALIDATED', 'UNVERIFIED']) assert.match(setupDisplayLabel(state, 'mt5'), /not executable/i);
});

test('focusing another or invalidated pattern cannot misattribute the latest levels', () => {
  assert.equal(showSetupLevels('CURRENT', 'latest', null), true);
  assert.equal(showSetupLevels('CURRENT', 'latest', 'latest'), true);
  assert.equal(showSetupLevels('CURRENT', 'latest', 'older-invalidated'), false);
  assert.equal(showSetupLevels('NONE', 'latest', null), false);
  assert.equal(showSetupLevels('STALE', null, 'older'), false);
});

test('critical feed explanation remains outside collapsed diagnostics', async () => {
  const app = await readFile(new URL('../src/main.tsx', import.meta.url), 'utf8');
  assert.ok(app.indexOf('feed-summary') < app.indexOf('feed-critical'));
  assert.ok(app.indexOf('feed-critical') < app.indexOf('feed-details'));
  assert.match(app, /feedCritical &&/);
  assert.match(app, /feedState/);
});


test('non-current reference levels use subdued sidebar colors', async () => {
  const app = await readFile(new URL('../src/main.tsx', import.meta.url), 'utf8');
  for (const color of ['green', 'red', 'blue']) {
    assert.ok(app.includes(`setupState === 'CURRENT' ? 'text-${color}' : 'text-reference'`));
  }
});


test('compact summary distinguishes feed health from connection evidence', () => {
  assert.equal(connectionLabel('CONNECTED'), 'Connected');
  assert.equal(connectionLabel('DISCONNECTED'), 'Disconnected');
  for (const unknown of ['UNVERIFIED', '', null, undefined, 'unexpected']) assert.equal(connectionLabel(unknown), 'Connection unknown');
});


test('compact health deduplicates revision details and preserves other critical conditions', async () => {
  const a = 'a'.repeat(64), b = 'b'.repeat(64), c = 'c'.repeat(64);
  const conflict = `conflicting duplicate candle at 2026-11-12T12:30:00; existing batch ${a}, incoming batch ${b}; revision unresolved`;
  const conflict2 = `conflicting duplicate candle at 2026-11-12T12:30:00; existing batch ${a}, incoming batch ${c}; revision unresolved`;
  const reasons = [conflict, conflict2, '1 candle revision(s) remain unresolved in the persistent ledger.', 'Exporter heartbeat has not advanced recently.', 'MT5 history synchronization is not verified.'];
  const summary = summarizeFeedReasons(reasons);
  assert.deepEqual(summary, ['Unresolved candle revision; see Feed details.', 'Exporter heartbeat has not advanced recently.', 'MT5 history synchronization is not verified.']);
  assert.ok(!summary.join(' ').includes(a));
  assert.deepEqual(summarizeFeedReasons(null), []);
  const app = await readFile(new URL('../src/main.tsx', import.meta.url), 'utf8');
  assert.ok(app.includes("feedReasons.join(' · ')"));
  assert.ok(app.includes("mt5Status?.reasons?.join(' · ')"), 'full original reasons remain in expandable details');
});


test('pattern chart filter keeps only explicit currently confirmed statuses without mutating source', () => {
  const records = [{id:'a',status:'FORMING'},{id:'b',status:'CONFIRMED'},{id:'c',status:'INVALIDATED'},{id:'d',status:'CONFIRMED'}];
  assert.deepEqual(selectChartPatterns(records, 'all').map(p => p.id), ['a','b','c','d']);
  assert.deepEqual(selectChartPatterns(records, 'confirmed').map(p => p.id), ['b','d']);
  assert.deepEqual(selectChartPatterns([], 'confirmed'), []);
  assert.deepEqual(records.map(p => p.id), ['a','b','c','d']);
});

test('gap classifications are source-reported, unknown or missing values do not become verified', () => {
  assert.deepEqual(summarizeGapClassifications(undefined), ['Gap classifications unavailable.']);
  assert.deepEqual(summarizeGapClassifications([]), ['No gap periods recorded.']);
  assert.deepEqual(summarizeGapClassifications([{classification:'UNKNOWN_SESSION_OR_MISSING'},{classification:'UNKNOWN'},{classification:'VERIFIED_SESSION_CLOSURE'},{classification:'RECOVERABLE_HISTORY_GAP'},{classification:'SOURCE_DATA_CONFLICT'},{classification:'VERIFIED_BROKER_NO_BAR'},{classification:'unrecognized'},{}]), ['Unknown session/missing-data gap: 2','Verified closure: 1','Recoverable history gap: 1','Source data conflict: 1','Verified broker no-bar: 1','Unclassified gap: 2']);
});

test('dashboard exposes bounded, expandable feed evidence and a chart-only pattern filter', async () => {
  const app = await readFile(new URL('../src/main.tsx', import.meta.url), 'utf8');
  const chart = await readFile(new URL('../src/Chart.tsx', import.meta.url), 'utf8');
  const styles = await readFile(new URL('../src/styles.css', import.meta.url), 'utf8');
  assert.match(app, /<details className="feed-details">/);
  assert.ok(app.indexOf('feed-critical') < app.indexOf('feed-details'));
  assert.match(app, /Gap periods:.*gapClassifications/);
  assert.match(app, /Pattern lines/);
  assert.match(chart, /selectChartPatterns\(data.patterns, patternLineMode\)/);
  assert.match(styles, /\.feed-details div\{max-height:9rem;overflow-y:auto/);
});


test('broker risk requires the current MT5 feed and exact symbol, timeframe, and snapshot', () => {
  const risk = {instrument: 'EURUSDm', timeframe: 'H1', snapshot_sha256: 'snapshot-a'};
  assert.equal(brokerRiskMatchesSnapshot(risk, 'mt5', 'EURUSDm', 'H1', 'snapshot-a', true), true);
  assert.equal(brokerRiskMatchesSnapshot(risk, 'mt5', 'EURUSDm', 'H1', 'snapshot-b', true), false);
  assert.equal(brokerRiskMatchesSnapshot(risk, 'mt5', 'XAUUSDm', 'H1', 'snapshot-a', true), false);
  assert.equal(brokerRiskMatchesSnapshot(risk, 'mt5', 'EURUSDm', 'M15', 'snapshot-a', true), false);
  assert.equal(brokerRiskMatchesSnapshot(risk, 'exness', 'EURUSDm', 'H1', 'snapshot-a', true), false);
  assert.equal(brokerRiskMatchesSnapshot(risk, 'mt5', 'EURUSDm', 'H1', 'snapshot-a', false), false);
  assert.equal(brokerRiskMatchesSnapshot(risk, 'mt5', 'EURUSDm', 'H1', null, true), false);
  assert.equal(brokerRiskMatchesSnapshot(null, 'mt5', 'EURUSDm', 'H1', 'snapshot-a', true), false);
});

test('broker-risk panel remains research-only and binds results to current analysis settings', async () => {
  const main = await readFile(new URL('../src/main.tsx', import.meta.url), 'utf8');
  assert.match(main, /BROKER RISK — UNVERIFIED/);
  assert.match(main, /Research estimates only · not executable/);
  assert.match(main, /brokerRisk\?\.requestKey === riskRequestParams\(source, symbol, timeframe, settings, appliedRiskBudget\)/);
  assert.match(main, /Unavailable costs are not zero/);
  assert.match(main, /Illustrative risk budget \(USD\)/);
  assert.match(main, /Price-distance reward \/ risk \(ratio\)/);
  assert.match(main, /Gross monetary reward \/ risk \(ratio\)/);
});


test('setup levels disclose snapshot ATR recalculation without implying executed prices', async () => {
  const app = await readFile(new URL('../src/main.tsx', import.meta.url), 'utf8');
  assert.match(app, /Reference levels are recalculated from the displayed snapshot/);
  assert.match(app, /stop and target use the latest ATR/);
  assert.match(app, /not recorded execution levels/);
});


test('illustrative budget is finite, positive, bounded and tied to the request', () => {
  for (const v of ['', ' ', '0', '-1', 'NaN', 'Infinity', '1000000.01']) assert.equal(parseRiskBudget(v), null);
  assert.equal(parseRiskBudget('1.06'), 1.06);
  assert.equal(parseRiskBudget('1000000'), 1000000);
  const first = new URLSearchParams(riskRequestParams('mt5', 'EURUSDm', 'H1', {left: 3}, 1.06));
  const second = new URLSearchParams(riskRequestParams('mt5', 'EURUSDm', 'H1', {left: 3}, 10));
  assert.equal(first.get('risk_budget_usd'), '1.06');
  assert.notEqual(first.toString(), second.toString());
  assert.equal(second.get('symbol'), 'EURUSDm');
  assert.equal(second.get('timeframe'), 'H1');
});

test('setup age counts only subsequent supplied completed bars, with absent timestamps unavailable', () => {
  const indicators = ['2026-01-01T01:00:00', '2026-01-01T02:00:00', '2026-01-01T03:00:00'].map(available_at_timestamp => ({available_at_timestamp}));
  assert.equal(barsSinceConfirmation('2026-01-01T01:00:00', indicators), 2);
  assert.equal(barsSinceConfirmation('2026-01-01T03:00:00', indicators), 0);
  assert.equal(barsSinceConfirmation('2026-01-01T04:00:00', indicators), null);
  assert.equal(barsSinceConfirmation(null, indicators), null);
  assert.equal(barsSinceConfirmation('bad', indicators), null);
});

test('budget edits hide older risk responses and source labels disclose setup limits', async () => {
  const app = await readFile(new URL('../src/main.tsx', import.meta.url), 'utf8');
  assert.match(app, /parsedRiskBudget === appliedRiskBudget/);
  assert.match(app, /brokerRisk\?\.risk_budget === appliedRiskBudget/);
  assert.match(app, /No age-based expiry is applied/);
  assert.match(app, /Bars since confirmation/);
  assert.match(app, /Latest candle open:/);
  assert.match(app, /does not verify account funds, position size or execution/);
});


test('snapshot sets must match the selected source, market, timeframe and settings', () => {
  const settings = {left: 3, right: 3, risk_reward: 2};
  const selection = {source: 'mt5', symbol: 'EURUSDm', timeframe: 'H1', settings};
  const bars = {source: 'mt5', symbol: 'EURUSDm', timeframe: 'H1', snapshot_sha256: 'a'.repeat(64)};
  const analysis = {...bars, analysis_config: {...settings, contract_size: null}};
  assert.equal(snapshotResponsesMatch(bars, [analysis, analysis, analysis], selection), true);
  for (const modified of [
    {...analysis, timeframe: 'M15'}, {...analysis, symbol: 'XAUUSDm'}, {...analysis, source: 'exness'},
    {...analysis, snapshot_sha256: 'b'.repeat(64)}, {...analysis, analysis_config: {...settings, risk_reward: 3}},
    {...analysis, analysis_config: null},
  ]) assert.equal(snapshotResponsesMatch(bars, [analysis, modified, analysis], selection), false);
  assert.equal(snapshotResponsesMatch({...bars, snapshot_sha256: 'bad'}, [analysis, analysis, analysis], selection), false);
  assert.equal(snapshotResponsesMatch(bars, [analysis, analysis], selection), false);
});

test('display-collapsed reference prices are flagged without changing raw values', () => {
  const values = {entry: 1.000001, stop_loss: 0.9999994, take_profit: 1.0000042};
  assert.equal(pricesCollapseAtPrecision(values, 5), true);
  assert.deepEqual(values, {entry: 1.000001, stop_loss: 0.9999994, take_profit: 1.0000042});
  assert.equal(pricesCollapseAtPrecision({entry: 1.1, stop_loss: 1.0, take_profit: 1.3}, 5), false);
  assert.equal(pricesCollapseAtPrecision({entry: null, stop_loss: 1, take_profit: 2}, 5), false);
  assert.equal(pricesCollapseAtPrecision({entry: Infinity, stop_loss: 1, take_profit: 2}, 5), false);
});


test('analysis settings accept their defaults while preserving integer-only fields', () => {
  const integerFields = new Set(['left', 'right', 'min_touches', 'min_separation']);
  assert.equal(ANALYSIS_SETTING_FIELDS.length, Object.keys(DEFAULT_ANALYSIS_SETTINGS).length);
  for (const [key, , min, max, step] of ANALYSIS_SETTING_FIELDS) {
    const value = DEFAULT_ANALYSIS_SETTINGS[key];
    assert.ok(value >= min && value <= max, `${key} default within bounds`);
    if (integerFields.has(key)) {
      assert.equal(step, 1, `${key} remains integer-only`);
      assert.equal((value - min) % step, 0, `${key} default aligns with HTML step`);
    } else {
      assert.equal(step, 'any', `${key} accepts valid decimal values without a mismatched step grid`);
    }
  }
});


test('module replacement reuses the existing root for the same container', () => {
  let creates = 0;
  const container = {};
  const makeRoot = () => ({id: ++creates});
  const original = getOrCreateAppRoot(container, makeRoot);
  const afterReplacement = getOrCreateAppRoot(container, makeRoot);
  assert.equal(afterReplacement, original);
  assert.equal(creates, 1);
  const freshContainer = {};
  assert.notEqual(getOrCreateAppRoot(freshContainer, makeRoot), original);
  assert.equal(creates, 2);
});
