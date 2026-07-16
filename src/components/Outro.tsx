import React from "react";
import { AbsoluteFill } from "remotion";
import { THEME } from "../theme";
import { Shieldy } from "../characters/Shieldy";

export const Outro: React.FC = () => (
  <AbsoluteFill style={{ background: THEME.navy, alignItems: "center", justifyContent: "center", gap: 30 }}>
    <Shieldy pose="happy" size={520} />
    <div style={{ color: THEME.gold, fontSize: 110, fontWeight: 900, fontFamily: "Arial" }}>SHIELD UP!</div>
    <div style={{ color: THEME.white, fontSize: 52, fontFamily: "Arial" }}>{THEME.site}</div>
  </AbsoluteFill>
);
