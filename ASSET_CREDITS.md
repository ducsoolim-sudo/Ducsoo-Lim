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
`brand-intro.wav` is an original synthesized 2.8-second glass/mallet chime created for this project, without external recordings. `generate_brand_sound.py` reproduces its E-major four-note phrase, restrained inharmonic partials and short diffuse echo tail. It is separate from the stone-placement sound. Automatic playback is attempted only during the company intro; browser autoplay restrictions can prevent it, and entry is never gated on a tap.
