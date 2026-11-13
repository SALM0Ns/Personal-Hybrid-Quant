import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';

const source = await readFile(new URL('../src/chartScale.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } });
const { includeSetupPrices } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);

test('autoscale includes a target below visible candles without changing price precision', () => {
  const base = {priceRange: {minValue: 1.105, maxValue: 1.110}, margins: {above: 3, below: 4}};
  const result = includeSetupPrices(base, [1.10657, 1.11033, 1.09904]);
  assert.deepEqual(result.priceRange, {minValue: 1.09904, maxValue: 1.11033});
  assert.deepEqual(result.margins, base.margins);
  assert.deepEqual(base.priceRange, {minValue: 1.105, maxValue: 1.110});
});

test('autoscale includes a target above visible candles and respects finite inputs', () => {
  const base = {priceRange: {minValue: 3900.1, maxValue: 3910.2}};
  assert.deepEqual(includeSetupPrices(base, [3905, 3897.123, 3920.456]).priceRange,
    {minValue: 3897.123, maxValue: 3920.456});
  assert.equal(includeSetupPrices(base, [null, undefined, NaN, Infinity]), base);
  assert.equal(includeSetupPrices(null, [1.1]), null);
});
