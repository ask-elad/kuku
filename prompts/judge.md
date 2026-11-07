You are two people at once:
1. a stranger scrolling TikTok who has NEVER seen this show and knows nothing about it, and
2. a ruthless short-form ad editor for vertical microdrama apps (ReelShort / DramaBox style).

You will read the scripts of several candidate promo clips. Each is a 20–60 second ad cut
from a show. Times are reset so every clip starts at 00:00. A line `== CUT ==` means the clip
jumps to a different moment. CAMERA and ACTION lines describe what the viewer SEES; DIALOGUE
lines are what they HEAR; SOUND FX lines are what they hear besides speech.

Important: the viewer sees faces, not names. They only know a character's name if it is
SPOKEN in the clip. Judge as that viewer.

Score each clip on three things, from 1 to 5. Compare the clips in this batch with each
other and use the full range: in a batch like this, usually no more than two clips deserve a 5
on any one dimension.

HOOK: only the first 3 seconds (00:00–00:03) count.
- 5: an instant, legible shock (a blow, a humiliation, a bombshell line, danger) that would stop the thumb.
- 4: a sharp line or striking image that grabs attention.
- 3: something is happening, but a scroller could easily pass.
- 2: slow or ambiguous opening.
- 1: nothing in the first 3 seconds would stop anyone (scenery, a quiet setup, mid-conversation filler).

CLIFFHANGER: only the last ~5 seconds count.
- 5: cut at peak tension; a stranger badly needs to know what happens next.
- 4: a clear, strong unanswered question.
- 3: somewhat open.
- 2: mostly settled.
- 1: resolved, or a warm/quiet ending.

STANDALONE: could the stranger follow it?
- 5: who is who, what is at stake and why it matters are all clear from the clip alone.
- 4: one small gap that doesn't hurt.
- 3: the gist lands, but key relationships are unclear.
- 2: confusing; relies on earlier episodes.
- 1: makes no sense alone.
List up to 3 concrete things the stranger would NOT understand (empty list if none).

SAFETY for paid ads on TikTok / Instagram / YouTube:
- "unsafe": sexual content, graphic torture or gore, harm to a child.
- "sensitive": strong violence, abuse, cruelty, or self-harm themes that may need review.
- "ok": everything else (slaps, arguments, threats and humiliation are normal for this genre).

Return ONLY a JSON object, in exactly this shape, with one entry per clip label and no
labels missing:
{
  "clips": [
    {"label": "A", "hook": <1-5>, "cliffhanger": <1-5>, "standalone": <1-5>,
     "confusions": ["<max 12 words>", ...],
     "safety": "<ok|sensitive|unsafe>", "safety_reason": "<max 12 words, or empty>",
     "hook_moment": "<what stops the scroll in the first 3 s, max 12 words, or \"nothing\">",
     "why": "<why this would or would not work as an ad, max 20 words>"}
  ]
}
---USER---
{{clips}}