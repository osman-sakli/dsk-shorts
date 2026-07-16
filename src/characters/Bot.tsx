import React from "react";
import { THEME } from "../theme";

export const Bot: React.FC<{ pose?: string; size?: number }> = ({ pose = "neutral", size = 370 }) => {
  const face = pose === "shock" ? "?" : pose === "happy" ? "^_^" : "o_o";
  return (
    <svg width={size} height={size} viewBox="-140 -170 280 320">
      <line x1="0" y1="-160" x2="0" y2="-120" stroke={THEME.navy} strokeWidth="9" />
      <circle cx="0" cy="-160" r="14" fill={THEME.gold} stroke={THEME.navy} strokeWidth="7" />
      <rect x="-100" y="-120" width="200" height="180" rx="60" fill="#E9EDF5" stroke={THEME.navy} strokeWidth="10" />
      <rect x="-70" y="-90" width="140" height="100" rx="24" fill={THEME.navy} />
      <text x="0" y="-25" textAnchor="middle" fontFamily="monospace" fontSize="44" fill={THEME.goldSoft}>{face}</text>
      <rect x="-70" y="60" width="140" height="70" rx="24" fill="#D7DDE9" stroke={THEME.navy} strokeWidth="9" />
      <circle cx="-95" cy="0" r="18" fill="#D7DDE9" stroke={THEME.navy} strokeWidth="8" />
      <circle cx="95" cy="0" r="18" fill="#D7DDE9" stroke={THEME.navy} strokeWidth="8" />
      {pose === "happy" && <text x="-110" y="-105" fontSize="34" fill={THEME.gold}>*</text>}
    </svg>
  );
};
