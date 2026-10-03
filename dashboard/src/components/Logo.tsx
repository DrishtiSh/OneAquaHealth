import { useId } from "react";

// A water droplet with a health "pulse" line through it -- same design as
// src/app/icon.svg (the browser favicon), reimplemented as a component so it
// can be reused at any size/color context (header, login, signup).
export default function Logo({ size = 32, className = "" }: { size?: number; className?: string }) {
  const gradientId = useId();

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      className={className}
      role="img"
      aria-label="OneAquaHealth logo"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#2dd4bf" />
          <stop offset="100%" stopColor="#0d9488" />
        </linearGradient>
      </defs>
      <path
        d="M12 21.5c4.97 0 9-3.694 9-8.25C21 8.5 12 2 12 2S3 8.5 3 13.25c0 4.556 4.03 8.25 9 8.25z"
        fill={`url(#${gradientId})`}
      />
      <path
        d="M5.5 13.6h2.6l1.3-2.6 1.7 5.2 1.7-6.8 1.3 4.2h4.4"
        fill="none"
        stroke="#ffffff"
        strokeWidth={1.4}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
