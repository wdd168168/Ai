/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js}'],
  theme: {
    extend: {
      colors: {
        ink: { 950: '#08090c', 900: '#0c0e13', 850: '#11141b', 800: '#161a23', 700: '#1f2531', 600: '#2b3342' },
        line: '#232b39',
        accent: { DEFAULT: '#4fd1c5', dim: '#2c7a75', soft: '#7ef0e3' },
        warn: '#f2b34b',
        danger: '#ef6b6b',
        ok: '#63d68b',
      },
      fontFamily: {
        sans: ['"Inter"', '"Noto Sans SC"', '"Noto Sans Khmer"', '"Noto Sans Thai"', '"Noto Sans"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
}
