import React from "react";
import { Composition, staticFile } from "remotion";
import { Short, totalFrames, Script } from "./Short";
import { VIDEO } from "./theme";
// Register one composition per script JSON. Add imports as you add scripts.
import s001 from "../content/scripts/001-knight-rule-1.json";
import s002 from "../content/scripts/002-glitch-free-robux.json";
import s003 from "../content/scripts/003-bot-vegetarian-sharks.json";
import s004 from "../content/scripts/004-would-you-tap-iphone.json";
import s005 from "../content/scripts/005-badge-friday-1.json";
import s006 from "../content/scripts/006-glitch-what-school.json";
import s007 from "../content/scripts/007-bot-homework.json";
import s008 from "../content/scripts/008-knight-rule-2-passwords.json";
import s009 from "../content/scripts/009-glitch-from-school.json";
import s010 from "../content/scripts/010-bot-voice-clone.json";

const scripts = [s001, s002, s003, s004, s005, s006, s007, s008, s009, s010] as Script[];

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
