import React from "react";
import { THEME } from "../theme";

// Placeholder SVG rig — replace with final art (see Character Bible).
export const Shieldy: React.FC<{ pose?: string; size?: number }> = ({ pose = "neutral", size = 420 }) => {
  const mouth = pose === "happy" ? "M -40 55 Q 0 95 40 55" : pose === "shock" ? "M -18 60 A 18 14 0 1 0 18 60 A 18 14 0 1 0 -18 60" : "M -30 62 Q 0 78 30 62";
  return (
    <svg width={size} height={size} viewBox="-150 -170 300 340">
      <path d="M -95 -40 Q -140 80 -70 130 L -60 100 Q -100 50 -80 -30 Z" fill={THEME.navy2} />
      <path d="M 0 -150 C 80 -130 110 -110 110 -60 C 110 40 60 110 0 150 C -60 110 -110 40 -110 -60 C -110 -110 -80 -130 0 -150 Z"
        fill={THEME.gold} stroke={THEME.navy} strokeWidth="10" />
      <path d="M -70 -95 Q 0 -125 70 -95 L 70 -70 Q 0 -95 -70 -70 Z" fill={THEME.navy} />
      <circle cx="-38" cy="-15" r={pose === "shock" ? 22 : 17} fill={THEME.navy} />
      <circle cx="38" cy="-15" r={pose === "shock" ? 22 : 17} fill={THEME.navy} />
      <circle cx="-32" cy="-21" r="6" fill="#fff" />
      <circle cx="44" cy="-21" r="6" fill="#fff" />
      <path d={mouth} fill={pose === "shock" ? THEME.navy : "none"} stroke={THEME.navy} strokeWidth="9" strokeLinecap="round" />
      <circle cx="-118" cy="30" r="16" fill={THEME.gold} stroke={THEME.navy} strokeWidth="8" />
      <circle cx="118" cy="30" r="16" fill={THEME.gold} stroke={THEME.navy} strokeWidth="8" />
      <ellipse cx="-40" cy="160" rx="20" ry="14" fill={THEME.navy} />
      <ellipse cx="40" cy="160" rx="20" ry="14" fill={THEME.navy} />
    </svg>
  );
};
