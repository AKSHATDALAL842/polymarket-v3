/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        mono: ['"JetBrains Mono"', 'monospace'],
        condensed: ['"Barlow Condensed"', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
