import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Keep the pinned, directly imported icons out of the dependency prebundle.
const icons = [
  'activity', 'arrow-down-right', 'arrow-up-right', 'chart-column', 'chevron-down',
  'circle-help', 'clock-3', 'crosshair', 'layers', 'refresh-cw', 'shield-alert',
  'sliders-horizontal',
];

export default defineConfig({
  plugins: [react()],
  optimizeDeps: {
    exclude: ['lucide-react', ...icons.map(icon => `lucide-react/dist/esm/icons/${icon}.js`)],
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: { '/api': process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000' },
  },
});
