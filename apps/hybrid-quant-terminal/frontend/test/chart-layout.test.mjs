import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import assert from 'node:assert/strict';

test('a tall risk panel does not stretch the chart and responsive chart minimums remain', async () => {
  const css = await readFile(new URL('../src/styles.css', import.meta.url), 'utf8');
  const grid = css.match(/\.terminal-grid\{([^}]*)\}/)?.[1] ?? '';
  assert.match(grid, /(?:^|;)align-items:start(?:;|$)/);
  assert.match(css, /\.chart-body\{[^}]*min-height:455px/);
  assert.match(css, /@media\(max-width:1100px\)[\s\S]*?\.chart-body,\.chart-state\{min-height:430px\}/);
  assert.match(css, /@media\(max-width:760px\)[\s\S]*?\.chart-body,\.chart-state\{min-height:380px\}/);
});
