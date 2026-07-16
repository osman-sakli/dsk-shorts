import React from "react";
import { THEME } from "../theme";

export const SpeechBubble: React.FC<{ text: string; flip?: boolean }> = ({ text, flip }) => (
  <div style={{
    background: THEME.white, color: THEME.navy, borderRadius: 44,
    border: `8px solid ${THEME.navy}`, padding: "36px 48px",
    fontSize: 58, fontWeight: 800, fontFamily: "Arial, sans-serif",
    maxWidth: 860, lineHeight: 1.15, textAlign: "center",
    boxShadow: "0 12px 0 rgba(0,0,0,0.18)",
    transform: flip ? "translateX(-30px)" : "translateX(30px)",
  }}>{text}</div>
);
