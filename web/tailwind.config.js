/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Bright forensic teal-cyan. Used for links, active states and
        // primary actions only — everything else stays neutral.
        accent: {
          50: '#effcfa',
          100: '#d5f7f2',
          200: '#aeede7',
          300: '#79dfd8',
          400: '#3cc7c4',
          500: '#17aaa8',
          600: '#0d8a89',
          700: '#0f6f70',
          800: '#11595b',
          900: '#124a4c',
          950: '#062a2c',
        },
        // Cool ink neutrals with a slight green cast to pair with the accent.
        ink: {
          50: '#f6f8f8',
          100: '#ebeff0',
          200: '#d6dddf',
          300: '#b4c0c3',
          400: '#8b9da2',
          500: '#6b7f85',
          600: '#566970',
          700: '#47565c',
          800: '#3d494e',
          900: '#363f43',
          925: '#242c2f',
          950: '#161c1e',
        },
      },
      fontFamily: {
        // Inter Variable + JetBrains Mono are bundled locally via fontsource
        // (see main.tsx) — no webfont fetches on air-gapped intranets.
        // CJK text falls through to the platform's system fonts.
        sans: [
          'Inter Variable',
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'PingFang SC',
          'Hiragino Sans GB',
          'Microsoft YaHei',
          'Noto Sans CJK SC',
          'sans-serif',
        ],
        mono: [
          'JetBrains Mono',
          'ui-monospace',
          'SFMono-Regular',
          'SF Mono',
          'Menlo',
          'Consolas',
          'Liberation Mono',
          'monospace',
        ],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
      boxShadow: {
        card: '0 1px 2px rgba(16, 24, 28, 0.05), 0 1px 3px rgba(16, 24, 28, 0.07)',
        'card-hover': '0 4px 10px rgba(16, 24, 28, 0.08), 0 1px 3px rgba(16, 24, 28, 0.08)',
        pop: '0 10px 30px rgba(16, 24, 28, 0.16), 0 2px 6px rgba(16, 24, 28, 0.10)',
        drawer: '-12px 0 40px rgba(16, 24, 28, 0.18)',
      },
      animation: {
        'fade-in': 'fadeIn 0.18s ease-out',
        rise: 'rise 0.26s ease-out both',
        'slide-in-right': 'slideInRight 0.24s cubic-bezier(0.32, 0.72, 0.24, 1)',
        shimmer: 'shimmer 1.8s linear infinite',
        'scale-in': 'scaleIn 0.16s ease-out',
        'blink-soft': 'blinkSoft 2.2s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        rise: {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        slideInRight: {
          '0%': { opacity: '0', transform: 'translateX(48px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        scaleIn: {
          '0%': { opacity: '0', transform: 'translate(-50%, -50%) scale(0.97)' },
          '100%': { opacity: '1', transform: 'translate(-50%, -50%) scale(1)' },
        },
        blinkSoft: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.35' },
        },
      },
    },
  },
  plugins: [require('@tailwindcss/forms')],
};
