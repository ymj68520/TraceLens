import { useId } from 'react';

interface BrandLogoProps {
  /** Rendered edge length in px (the mark is square). */
  size?: number;
  className?: string;
}

/**
 * TraceLens brand mark: a magnifier lens over a forensic trace waveform —
 * the lens examines the trace. Tile background is the brand teal gradient;
 * the mark itself stays white so it reads on any surface and any size.
 */
export default function BrandLogo({ size = 28, className }: BrandLogoProps) {
  const gid = useId();
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      className={className}
      role="img"
      aria-label="TraceLens"
    >
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#17aaa8" />
          <stop offset="100%" stopColor="#0d8a89" />
        </linearGradient>
      </defs>
      <rect width="48" height="48" rx="12" fill={`url(#${gid})`} />
      <circle cx="21" cy="21" r="10.5" fill="none" stroke="#ffffff" strokeWidth="3.2" />
      <line
        x1="29.2"
        y1="29.2"
        x2="37.4"
        y2="37.4"
        stroke="#ffffff"
        strokeWidth="3.2"
        strokeLinecap="round"
      />
      <path
        d="M12 21 H16 L18.5 15.5 L22 27 L24.5 21 H30"
        fill="none"
        stroke="#ffffff"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.94"
      />
    </svg>
  );
}
