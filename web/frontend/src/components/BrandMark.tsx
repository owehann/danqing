import React, { useId } from "react";

interface BrandMarkProps {
  variant?: "mark" | "seal";
  size?: number;
  className?: string;
}

export function BrandMark({
  variant = "mark",
  size = 20,
  className = "",
}: BrandMarkProps): React.ReactElement {
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, "");

  if (variant === "seal") {
    const paperId = `dq-seal-paper-${uid}`;
    const danId = `dq-seal-dan-${uid}`;
    const qingId = `dq-seal-qing-${uid}`;
    const jadeId = `dq-seal-jade-${uid}`;
    const danClipId = `dq-seal-dan-clip-${uid}`;
    const qingClipId = `dq-seal-qing-clip-${uid}`;

    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 128 128"
        fill="none"
        className={className || undefined}
        aria-hidden="true"
      >
        <defs>
          <linearGradient id={paperId} x1="12" y1="8" x2="116" y2="120" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#FDFCF8" />
            <stop offset="100%" stopColor="#F1ECE0" />
          </linearGradient>
          <linearGradient id={danId} x1="24" y1="24" x2="78" y2="78" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#E4553C" />
            <stop offset="100%" stopColor="#C23722" />
          </linearGradient>
          <linearGradient id={qingId} x1="50" y1="50" x2="104" y2="104" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#257291" />
            <stop offset="100%" stopColor="#164663" />
          </linearGradient>
          <linearGradient id={jadeId} x1="50" y1="50" x2="80" y2="80" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#4BBAA9" />
            <stop offset="100%" stopColor="#278980" />
          </linearGradient>
          <clipPath id={danClipId}>
            <circle cx="52" cy="52" r="27" />
          </clipPath>
          <clipPath id={qingClipId}>
            <rect x="50" y="50" width="50" height="50" rx="13" />
          </clipPath>
        </defs>
        <rect
          x="6"
          y="6"
          width="116"
          height="116"
          rx="28"
          fill={`url(#${paperId})`}
          stroke="#D6CFC1"
          strokeWidth="2.5"
        />
        <rect x="50" y="50" width="50" height="50" rx="13" fill={`url(#${qingId})`} />
        <circle cx="52" cy="52" r="27" fill={`url(#${danId})`} />
        <g clipPath={`url(#${danClipId})`}>
          <rect x="50" y="50" width="50" height="50" rx="13" fill={`url(#${jadeId})`} />
          <rect x="50" y="50" width="50" height="50" rx="13" stroke="#FCFBF7" strokeWidth="2.4" />
        </g>
        <g clipPath={`url(#${qingClipId})`}>
          <circle cx="52" cy="52" r="27" stroke="#FCFBF7" strokeWidth="2.4" />
        </g>
      </svg>
    );
  }

  const danId = `dq-mark-dan-${uid}`;
  const qingId = `dq-mark-qing-${uid}`;
  const danClipId = `dq-mark-clip-${uid}`;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      className={className || undefined}
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={danId} x1="8" y1="8" x2="42" y2="42" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#E6583E" />
          <stop offset="100%" stopColor="#C43823" />
        </linearGradient>
        <linearGradient id={qingId} x1="22" y1="22" x2="58" y2="58" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#2B8E92" />
          <stop offset="100%" stopColor="#19556C" />
        </linearGradient>
        <clipPath id={danClipId}>
          <circle cx="25" cy="25" r="21" />
        </clipPath>
      </defs>
      <rect x="22" y="22" width="38" height="38" rx="10" fill={`url(#${qingId})`} />
      <circle cx="25" cy="25" r="21" fill={`url(#${danId})`} />
      <g clipPath={`url(#${danClipId})`}>
        <rect x="22" y="22" width="38" height="38" rx="10" fill="#FAF6EE" />
      </g>
    </svg>
  );
}
