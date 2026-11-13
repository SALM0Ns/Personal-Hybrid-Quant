import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import assert from 'node:assert/strict';

// Compare the selected deep imports with the pinned Lucide package's own exports.
test('dashboard icons resolve to the same implementations as Lucide named exports', async () => {
  const app = await readFile(new URL('../src/main.tsx', import.meta.url), 'utf8');
  const barrel = await readFile(new URL('../node_modules/lucide-react/dist/esm/lucide-react.js', import.meta.url), 'utf8');
  const expected = {
    Activity: 'activity', ArrowDownRight: 'arrow-down-right', ArrowUpRight: 'arrow-up-right',
    BarChart3: 'chart-column', ChevronDown: 'chevron-down', CircleHelp: 'circle-help',
    Clock3: 'clock-3', Crosshair: 'crosshair', Layers3: 'layers', RefreshCw: 'refresh-cw',
    ShieldAlert: 'shield-alert', SlidersHorizontal: 'sliders-horizontal',
  };
  assert.doesNotMatch(app, /from ['"]lucide-react['"]/);
  for (const [name, filename] of Object.entries(expected)) {
    assert.ok(app.includes(`import ${name} from 'lucide-react/dist/esm/icons/${filename}.js';`), `${name} import`);
    assert.match(barrel, new RegExp(`export \\{[^\\n]*\\bas ${name}\\b[^\\n]*\\} from '\\./icons/${filename}\\.js';`), `${name} package mapping`);
  }
});
