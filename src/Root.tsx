import React from "react";
import { Composition, staticFile } from "remotion";
import { Short, totalFrames, Script } from "./Short";
import { VIDEO } from "./theme";
// Register one composition per script JSON. Add imports as you add scripts.
import s001 from "../content/scripts/001-knight-rule-1.json";
import s002 from "../content/scripts/002-glitch-free-robux.json";
import s003 from "../content/scripts/003-bot-vegetarian-sharks.json";

const scripts = [s001, s002, s003] as Script[];

export const Root: React.FC = () => (
  <>
    {scripts.map((s) => (
      <Composition
        key={s.id}
        id={s.id}
        component={Short}
        durationInFrames={totalFrames(s)}
        fps={VIDEO.fps}
        width={VIDEO.width}
        height={VIDEO.height}
        defaultProps={{ script: s }}
      />
    ))}
  </>
);
