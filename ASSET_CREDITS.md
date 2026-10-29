# Audio source

`stone-placement.wav` is a trimmed and lightly processed excerpt from
**GoStoneSounds.ogg** by **billhails2**, published 2021-09-26 on Freesound:
https://freesound.org/people/billhails2/sounds/588317/

The source page labels the recording **Creative Commons 0 (CC0)**:
https://creativecommons.org/publicdomain/zero/1.0/

The author describes Yunzi Go stones on two boards; the last two impacts are on
a thin shin-kaya 19x19 board. We used the fifth impact, from the publicly provided
HQ MP3 preview (`588317_12616419-hq.mp3`), trimming 6.18–6.48 seconds, converting to
44.1 kHz mono PCM WAV, applying a 90 Hz high-pass filter, a final 100 ms fade, and
1.05 gain. The original recording was not made by this project. It is served from
our own static assets, not hotlinked. A synthesized impact remains only as a
network/decode fallback. Countdown and brand cues are original Web Audio tones.

## Studio signature
`brand-intro.wav` is an original synthesized 2.8-second glass/mallet chime created for this project, without external recordings. `generate_brand_sound.py` reproduces its E-major three-note phrase, restrained inharmonic partials and short diffuse echo tail. It is separate from the stone-placement sound. Automatic playback is attempted only during the company intro; browser autoplay restrictions can prevent it, and entry is never gated on a tap.

## Event cues — 2026-10-30
Match ready: E5–B5, 0.37 seconds. Game end: G#5–E5, 0.64 seconds. Original quiet sine cues, identical for win/loss; no external samples. Countdown/stone takes priority and stops a pending event cue. New game transitions only; no delayed replay after unlocking, reconnect or hidden tab. Brand audio v2 uses three notes at a reduced peak and stops when leaving the intro. Actual iPhone listening/autoplay acceptance remains pending.

### Studio signature v3
2026-10-30: 3.2-second original warm felt-mallet phrase E4–B4–E5. Rounded 18ms attacks, sparse harmonic partials, low quiet resonance and diffuse tail. Peak reduced to 0.43. The generated waveform has a 450ms cosine fade. Source generator reproduces the asset; v3 cache key and lower-register fallback are synchronized. Perceived quality and iPhone playback still require listening.
