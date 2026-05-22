"use client";

/**
 * Player headshot, served from our own /public/headshots/ — zero runtime
 * third-party dependency (master plan §2.1 + §3).
 *
 * Backend pre-downloads each player's headshot via
 * `scripts/download_headshots.py`, writes WebP files keyed by a slug, and
 * stores the slug in `players.headshot_path`. The frontend just reads
 * /headshots/{path}.
 *
 * Fallback: colored-initials circle. Always renders something — never
 * a broken-image icon.
 */
import Image from "next/image";
import { useState } from "react";

export interface PlayerAvatarProps {
  /** The player's full name (used for initials fallback). */
  name: string;
  /** Relative path under /headshots/, e.g. "lebron-james-1966.webp". */
  headshotPath?: string | null;
  size?: 24 | 32 | 48 | 64 | 96 | 128;
  className?: string;
}

const FALLBACK_COLORS = [
  "bg-rose-500",
  "bg-amber-500",
  "bg-emerald-500",
  "bg-sky-500",
  "bg-indigo-500",
  "bg-purple-500",
  "bg-pink-500",
  "bg-teal-500",
];

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length === 0) return "??";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function hashColor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) | 0;
  return FALLBACK_COLORS[Math.abs(h) % FALLBACK_COLORS.length];
}

export function PlayerAvatar({
  name,
  headshotPath,
  size = 48,
  className = "",
}: PlayerAvatarProps) {
  const [errored, setErrored] = useState(false);

  // Pick the right resolution. 96+ gets the @2x file.
  const useLarge = size >= 96;
  const src = headshotPath
    ? useLarge
      ? `/headshots/${headshotPath.replace(/\.webp$/, "@2x.webp")}`
      : `/headshots/${headshotPath}`
    : null;

  if (!src || errored) {
    const color = hashColor(name);
    return (
      <div
        className={`inline-flex items-center justify-center rounded-full text-white font-semibold ${color} ${className}`}
        style={{
          width: size,
          height: size,
          fontSize: Math.max(10, Math.floor(size / 2.5)),
        }}
        title={name}
        aria-label={name}
      >
        {initials(name)}
      </div>
    );
  }

  return (
    <Image
      src={src}
      alt={name}
      width={size}
      height={size}
      className={`rounded-full object-cover ${className}`}
      onError={() => setErrored(true)}
      unoptimized // Pre-resized WebPs at exact sizes — no further optimization needed
    />
  );
}
