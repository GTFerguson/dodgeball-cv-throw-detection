/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ground: 'var(--ground)',
        surface: {
          DEFAULT: 'var(--surface)',
          2: 'var(--surface-2)',
          3: 'var(--surface-3)',
        },
        ink: {
          DEFAULT: 'var(--ink)',
          mute: 'var(--ink-mute)',
          faint: 'var(--ink-faint)',
        },
        rule: {
          DEFAULT: 'var(--rule)',
          strong: 'var(--rule-strong)',
        },
        hit: { DEFAULT: 'var(--sig-hit)', soft: 'var(--sig-hit-soft)' },
        catch: { DEFAULT: 'var(--sig-catch)', soft: 'var(--sig-catch-soft)' },
        block: { DEFAULT: 'var(--sig-block)', soft: 'var(--sig-block-soft)' },
        miss: { DEFAULT: 'var(--sig-miss)', soft: 'var(--sig-miss-soft)' },
        open: { DEFAULT: 'var(--sig-open)', soft: 'var(--sig-open-soft)' },
        model: { DEFAULT: 'var(--sig-model)', soft: 'var(--sig-model-soft)' },
      },
      fontFamily: {
        sans: ['"Archivo Variable"', 'Archivo', 'Helvetica Neue', 'Arial', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      borderRadius: { DEFAULT: '2px', sm: '2px', md: '3px' },
      boxShadow: {
        panel: '0 1px 2px rgba(43,42,44,.05), 0 10px 28px -14px rgba(43,42,44,.18)',
      },
    },
  },
  plugins: [],
}
