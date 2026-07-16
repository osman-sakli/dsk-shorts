import React from "react";
import { THEME } from "../theme";

export const Glitch: React.FC<{ pose?: string; size?: number }> = ({ pose = "neutral", size = 380 }) => {
  const defeated = pose === "shock";
  return (
    <svg width={size} height={size} viewBox="-150 -150 300 300" opacity={defeated ? 0.75 : 1}>
      <path d="M -10 -130 C 60 -140 120 -90 110 -30 C 130 20 90 60 100 100 C 60 130 20 100 -20 125 C -70 110 -60 70 -100 50 C -130 10 -110 -40 -120 -70 C -90 -120 -60 -115 -10 -130 Z"
        fill={THEME.purple} stroke={THEME.navy} strokeWidth="9" strokeDasharray={defeated ? "14 10" : "0"} />
      <rect x="-70" y="-90" width="22" height="22" fill={THEME.navy2} opacity="0.5" />
      <rect x="50" y="-40" width="18" height="18" fill={THEME.navy2} opacity="0.5" />
      <rect x="-30" y="60" width="20" height="20" fill={THEME.navy2} opacity="0.5" />
      <path d="M -60 -25 Q -40 -40 -20 -25" stroke={THEME.goldSoft} strokeWidth="10" strokeLinecap="round" fill="none" />
      <path d="M 20 -25 Q 40 -40 60 -25" stroke={THEME.goldSoft} strokeWidth="10" strokeLinecap="round" fill="none" />
      <circle cx="-40" cy="-18" r="9" fill={THEME.goldSoft} />
      <circle cx="40" cy="-18" r="9" fill={THEME.goldSoft} />
      {defeated
        ? <ellipse cx="0" cy="45" rx="22" ry="28" fill={THEME.navy} />
        : <path d="M -50 35 Q 0 75 50 35 Q 30 55 10 50 Q 0 62 -12 50 Q -32 56 -50 35 Z" fill={THEME.navy} />}
    </svg>
  );
};
