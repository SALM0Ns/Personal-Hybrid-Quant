import type { AutoscaleInfo } from 'lightweight-charts';

/** Keep visible setup price lines in the candle autoscale without changing prices. */
export function includeSetupPrices(
  original: AutoscaleInfo | null,
  prices: ReadonlyArray<number | null | undefined>,
): AutoscaleInfo | null {
  if (original === null) return null;
  const finite = prices.filter((price): price is number => typeof price === 'number' && Number.isFinite(price));
  if (finite.length === 0) return original;
  return {
    ...original,
    priceRange: {
      minValue: Math.min(original.priceRange.minValue, ...finite),
      maxValue: Math.max(original.priceRange.maxValue, ...finite),
    },
  };
}
