import React from "react";
import { THEME } from "../theme";

export const Pixel: React.FC<{ pose?: string; size?: number }> = ({ pose = "neutral", size = 360 }) => {
  const mouth = pose === "happy" ? "M -35 55 Q 0 90 35 55" : pose === "shock" ? "M -16 58 A 16 13 0 1 0 16 58 A 16 13 0 1 0 -16 58" : "M -25 60 Q 0 72 25 60";
  return (
    <svg width={size} height={size} viewBox="-140 -150 280 300">
      <rect x="-95" y="-60" width="24" height="130" rx="12" fill={THEME.gold} />
      <rect x="-105" y="-115" width="210" height="230" rx="46" fill={THEME.teal} stroke={THEME.navy} strokeWidth="10" />
      <circle cx="-40" cy="-20" r={pose === "shock" ? 24 : 19} fill={THEME.navy} />
      <circle cx="42" cy="-20" r={pose === "shock" ? 24 : 19} fill={THEME.navy} />
      <circle cx="-33" cy="-27" r="7" fill="#fff" />
      <circle cx="49" cy="-27" r="7" fill="#fff" />
      <path d={pose === "shock" ? "M -62 -62 L -18 -52" : "M -62 -52 L -18 -58"} stroke={THEME.navy} strokeWidth="9" strokeLinecap="round" />
      <path d={pose === "shock" ? "M 20 -52 L 64 -62" : "M 20 -58 L 64 -52"} stroke={THEME.navy} strokeWidth="9" strokeLinecap="round" />
      <path d={mouth} fill={pose === "shock" ? THEME.navy : "none"} stroke={THEME.navy} strokeWidth="8" strokeLinecap="round" />
      <rect x="60" y="55" width="58" height="95" rx="12" fill={THEME.navy} transform="rotate(-12 89 102)" />
      <rect x="68" y="66" width="42" height="66" rx="6" fill={THEME.goldSoft} transform="rotate(-12 89 102)" />
    </svg>
  );
};
