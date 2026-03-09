/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        navy: {
          950: '#0d0d1a',
          900: '#1a1a2e',
          800: '#16213e',
          700: '#0f3460',
        },
        accent: '#e94560',
      },
    },
  },
  plugins: [],
}
