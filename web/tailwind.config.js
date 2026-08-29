/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Restrained forensic-teal accent. Used for links, active states and
        // primary actions only — everything else stays neutral.
        accent: {
          50: '#effaf9',
          100: '#d7f2f0',
          200: '#b3e5e2',
          300: '#82d1cd',
          400: '#4db6b1',
          500: '#2e9b96',
          600: '#227d7a',
          700: '#1f6563',
          800: '#1d5250',
          900: '#1c4443',
          950: '#0b2626',
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
        sans: [
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'PingFang SC',
          'Microsoft YaHei',
          'sans-serif',
        ],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
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
        rise: 'rise 0.22s ease-out',
        'slide-in-right': 'slideInRight 0.24s cubic-bezier(0.32, 0.72, 0.24, 1)',
        shimmer: 'shimmer 1.8s linear infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        rise: {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
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
      },
    },
  },
  plugins: [require('@tailwindcss/forms')],
};
