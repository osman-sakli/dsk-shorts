import React from "react";
import { AbsoluteFill, Sequence, useCurrentFrame, interpolate } from "remotion";
import { THEME, VIDEO } from "./theme";
import { Shieldy } from "./characters/Shieldy";
import { Pixel } from "./characters/Pixel";
import { Glitch } from "./characters/Glitch";
import { Bot } from "./characters/Bot";
import { SpeechBubble } from "./components/SpeechBubble";
import { Outro } from "./components/Outro";

const CHAR: Record<string, React.FC<{ pose?: string; size?: number }>> = {
  SHIELDY: Shieldy, PIXEL: Pixel, GLITCH: Glitch, BOT: Bot,
};

export type Line = { who: string; text: string; pose?: string; durInFrames?: number };
export type Script = { id: string; title: string; scene?: string; lines: Line[] };

const LINE_FRAMES = 62; // ~2.05s default per line @30fps; tts.py timing can override
const OUTRO_FRAMES = 45;

export const totalFrames = (s: Script) =>
  s.lines.reduce((a, l) => a + (l.durInFrames ?? LINE_FRAMES), 0) + OUTRO_FRAMES;

export const Short: React.FC<{ script: Script }> = ({ script }) => {
  const frame = useCurrentFrame();
  let cursor = 0;
  const seqs = script.lines.map((l, i) => {
    const from = cursor;
    const dur = l.durInFrames ?? LINE_FRAMES;
    cursor += dur;
    return { ...l, from, dur, key: i };
  });
  const bg = interpolate(frame, [0, 30], [0.92, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ background: THEME.cloud }}>
      <AbsoluteFill style={{ transform: `scale(${bg})`, alignItems: "center", justifyContent: "flex-start", paddingTop: 90 }}>
        <div style={{ fontSize: 46, fontWeight: 900, color: THEME.navy, fontFamily: "Arial", background: THEME.goldSoft, padding: "14px 40px", borderRadius: 40 }}>
          {script.title}
        </div>
      </AbsoluteFill>
      {seqs.map((l) => {
        const C = CHAR[l.who] ?? Shieldy;
        const left = l.who === "PIXEL" || l.who === "BOT";
        return (
          <Sequence key={l.key} from={l.from} durationInFrames={l.dur}>
            <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", gap: 40, flexDirection: "column" }}>
              <SpeechBubble text={l.text} flip={left} />
              <div style={{ transform: left ? "scaleX(-1)" : undefined }}>
                <C pose={l.pose ?? (l.who === "GLITCH" ? "neutral" : "happy")} />
              </div>
            </AbsoluteFill>
          </Sequence>
        );
      })}
      <Sequence from={cursor} durationInFrames={OUTRO_FRAMES}>
        <Outro />
      </Sequence>
    </AbsoluteFill>
  );
};
