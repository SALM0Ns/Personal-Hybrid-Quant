import { useEffect, useRef } from 'react';
import { ColorType, CrosshairMode, LineStyle, createChart, type IChartApi, type ISeriesApi, type AutoscaleInfo, type Time } from 'lightweight-charts';
import type { Data, Pattern, Visibility } from './types';
import { chartTime, selectChartPatterns, showSetupLevels, type PatternLineMode, type SetupDisplayState } from './utils';
import { includeSetupPrices } from './chartScale';

type Props = { data: Data; visibility: Visibility; focus: Pattern | null; setupState: SetupDisplayState; patternLineMode: PatternLineMode; onRange?: () => void };
export default function Chart({ data, visibility, focus, setupState, patternLineMode }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const candles = useRef<ISeriesApi<'Candlestick'> | null>(null);
  useEffect(() => {
    if (!host.current) return;
    const coordinate = (timestamp: string) => chartTime(timestamp, data.time_basis);
    const instance = createChart(host.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: '#101823' }, textColor: '#718196', fontFamily: 'Inter, system-ui, sans-serif', fontSize: 11 },
      grid: { vertLines: { color: '#192535' }, horzLines: { color: '#192535' } },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: '#65758b', labelBackgroundColor: '#334155' }, horzLine: { color: '#65758b', labelBackgroundColor: '#334155' } },
      rightPriceScale: { borderColor: '#293647' }, timeScale: { borderColor: '#293647', timeVisible: true, secondsVisible: false },
      localization: { timeFormatter: (time: Time) => new Date((time as number) * 1000).toISOString().replace('T', ' ').slice(0, 16) + (data.time_basis === 'utc' ? ' UTC' : ' broker time') },
    });
    chart.current = instance;
    const precision = data.candles[0].close < 10 ? 5 : 3;
    const showLevels = Boolean(visibility.levels && data.analysis && showSetupLevels(setupState, data.analysis.pattern_id, focus?.id));
    const setupPrices = showLevels && data.analysis ? [data.analysis.entry, data.analysis.stop_loss, data.analysis.take_profit] : [];
    const series = instance.addCandlestickSeries({ priceFormat: { type: 'price', precision, minMove: 10 ** -precision }, upColor: '#39c5a0', downColor: '#ef717b', borderVisible: false, wickUpColor: '#39c5a0', wickDownColor: '#ef717b', autoscaleInfoProvider: (original: () => AutoscaleInfo | null) => includeSetupPrices(original(), setupPrices) });
    candles.current = series;
    series.setData(data.candles.map(c => ({ time: coordinate(c.timestamp), open: c.open, high: c.high, low: c.low, close: c.close })));
    const addLine = (key: 'ema20' | 'ema50', color: string) => {
      const line = instance.addLineSeries({ color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      line.setData(data.indicators.filter(item => item.timestamp >= data.candles[0].timestamp && item.timestamp <= data.candles[data.candles.length - 1].timestamp).map(item => item[key] === null ? ({ time: coordinate(item.timestamp) }) : ({ time: coordinate(item.timestamp), value: item[key] as number })));
    };
    if (visibility.ema20) addLine('ema20', '#e5bb69');
    if (visibility.ema50) addLine('ema50', '#9a94f7');
    if (visibility.zones) data.zones.forEach(zone => {
      const last = data.candles[data.candles.length - 1].timestamp;
      const start = data.candles.find(c => c.timestamp >= zone.last_updated_at_timestamp);
      if (!zone.last_updated_at_timestamp || !start || start.timestamp >= last) return;
      [zone.lower, zone.upper].forEach(price => {
        const line = instance.addLineSeries({ color: zone.kind === 'SUPPORT' ? '#369d8588' : '#d77c8588', lineWidth: 1, lineStyle: LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
        line.setData([{ time: coordinate(start.timestamp), value: price }, { time: coordinate(last), value: price }]);
      });
    });
    if (showLevels && data.analysis) {
      const reference = setupState !== 'CURRENT';
      const prefix = setupState === 'STALE' ? 'Stale' : setupState === 'HISTORICAL' ? 'Historical' : setupState === 'INVALIDATED' ? 'Invalidated' : setupState === 'UNVERIFIED' ? 'Unverified' : 'Analytical';
      [{ price: data.analysis.entry, title: `${prefix} entry`, color: '#39c5a0' }, { price: data.analysis.stop_loss, title: `${prefix} stop`, color: '#ef717b' }, { price: data.analysis.take_profit, title: `${prefix} target`, color: '#6ca7ff' }].forEach(level => {
        if (typeof level.price === 'number' && Number.isFinite(level.price)) series.createPriceLine({ price: level.price, color: reference ? 'rgba(143, 158, 170, 0.65)' : level.color, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: level.title });
      });
    }
    if (visibility.swings) {
      const times = new Set(data.candles.map(c => c.timestamp));
      series.setMarkers(data.swings.filter(s => times.has(s.pivot_timestamp)).map(s => ({ time: coordinate(s.pivot_timestamp), position: s.swing_type === 'HIGH' ? 'aboveBar' as const : 'belowBar' as const, color: s.swing_type === 'HIGH' ? '#ef8992' : '#64cab1', shape: s.swing_type === 'HIGH' ? 'arrowDown' as const : 'arrowUp' as const, text: '' })).sort((a, b) => Number(a.time) - Number(b.time)));
    }
    if (visibility.patterns) selectChartPatterns(data.patterns, patternLineMode).slice(-25).forEach(pattern => {
      try {
        if (pattern.anchor_1_timestamp < data.candles[0].timestamp || pattern.anchor_2_timestamp > data.candles[data.candles.length - 1].timestamp) return;
        const p1 = coordinate(pattern.anchor_1_timestamp), p2 = coordinate(pattern.anchor_2_timestamp);
        if (p1 >= p2) return;
        const line = instance.addLineSeries({ color: pattern.type === 'DOUBLE_TOP' ? '#e07f8999' : '#52c0a499', lineWidth: 1, lineStyle: LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
        line.setData([{time: p1, value: pattern.anchor_1_price}, {time: p2, value: pattern.anchor_2_price}]);
      } catch { /* An invalid pattern must not prevent the candles from rendering. */ }
    });
    instance.timeScale().fitContent();
    return () => { chart.current = null; candles.current = null; instance.remove(); };
  }, [data, visibility, focus, setupState, patternLineMode]);
  useEffect(() => {
    if (!focus || !chart.current) return;
    const first = data.candles.findIndex(c => c.timestamp >= focus.anchor_1_timestamp);
    const last = data.candles.findIndex(c => c.timestamp >= focus.anchor_2_timestamp);
    if (first < 0 || last < 0) return;
    chart.current.timeScale().setVisibleLogicalRange({ from: Math.max(0, first - 20), to: Math.min(data.candles.length + 5, last + 20) });
  }, [focus, data]);
  return <div className="chart-area" ref={host} aria-label="Interactive candlestick chart" />;
}
