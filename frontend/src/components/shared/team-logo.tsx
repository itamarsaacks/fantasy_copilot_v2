"use client";

/**
 * NBA team logo, served from our own /public/nba-logos/ — zero runtime
 * third-party dependency (master plan §3 + §2.A).
 *
 * Fallback: a colored monogram circle (3-letter abbr) so missing assets
 * never break the layout. As asset SVGs are added under
 * frontend/public/nba-logos/<ABBR>.svg the component picks them up
 * automatically.
 */
import Image from "next/image";
import { useState } from "react";

const TEAM_COLORS: Record<string, string> = {
  LAL: "bg-purple-700",
  BOS: "bg-emerald-700",
  GSW: "bg-blue-700",
  MIA: "bg-red-700",
  NYK: "bg-orange-600",
  PHX: "bg-orange-700",
  PHI: "bg-blue-800",
  MIL: "bg-emerald-800",
  DEN: "bg-blue-900",
  DAL: "bg-blue-600",
  // Default for the rest
};

export interface TeamLogoProps {
  abbr: string | null | undefined;
  size?: 16 | 24 | 32 | 48 | 64;
  className?: string;
}

const SIZE_PX = {
  16: 16,
  24: 24,
  32: 32,
  48: 48,
  64: 64,
};

export function TeamLogo({ abbr, size = 32, className = "" }: TeamLogoProps) {
  const [errored, setErrored] = useState(false);
  const safeAbbr = (abbr || "").toUpperCase();
  const px = SIZE_PX[size];

  if (!safeAbbr) {
    return (
      <div
        className={`inline-flex items-center justify-center rounded-full bg-slate-300 ${className}`}
        style={{ width: px, height: px }}
        aria-hidden
      />
    );
  }

  if (errored) {
    const color = TEAM_COLORS[safeAbbr] ?? "bg-slate-600";
    return (
      <div
        className={`inline-flex items-center justify-center rounded-full text-white font-semibold ${color} ${className}`}
        style={{
          width: px,
          height: px,
          fontSize: Math.max(8, Math.floor(px / 3)),
        }}
        title={safeAbbr}
      >
        {safeAbbr}
      </div>
    );
  }

  return (
    <Image
      src={`/nba-logos/${safeAbbr}.svg`}
      alt={`${safeAbbr} logo`}
      width={px}
      height={px}
      className={className}
      onError={() => setErrored(true)}
      unoptimized // SVGs don't benefit from next/image optimization
    />
  );
}
