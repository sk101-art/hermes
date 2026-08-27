import { defineConfig } from 'vite';

// HERMES frontend build configuration.
// Budget contract (docs/production-readiness.md): JS <= 185 KB uncompressed.
// Vite 8 here is rolldown-based: default minifier is oxc/rolldown (no esbuild).
// - target 'esnext' avoids syntax downleveling helpers (evergreen-only SPA).
export default defineConfig({
  build: {
    target: 'esnext',
    cssTarget: 'esnext',
    reportCompressedSize: false,
  },
});
