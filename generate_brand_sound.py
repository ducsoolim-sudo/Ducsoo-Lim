"""Render 13GO's original glass/mallet studio signature (no external samples)."""
import math
from pathlib import Path
import struct
import wave

RATE = 44100
DURATION = 2.8

def render(destination):
    output = [0.0] * int(RATE * DURATION)
    # E major, four light mallet attacks resolving to the octave.
    for start, frequency, level in [(0.04,659.255,.8),(.17,830.609,.65),(.31,987.767,.6),(.49,1318.51,.53)]:
        for i in range(int(RATE * 2.15)):
            t = i / RATE
            attack = 1 - math.exp(-t / .006)
            value = 0.0
            for ratio, strength, decay in [(1,1,.58),(2,.22,.28),(2.756,.075,.16),(4,.025,.10)]:
                value += strength * math.sin(2 * math.pi * frequency * ratio * t) * math.exp(-t / decay)
            value *= attack * level
            for delay, gain in [(0,1),(.073,.13),(.139,.095),(.227,.06),(.347,.035)]:
                index = int((start+delay)*RATE)+i
                if index < len(output):
                    output[index] += value * gain
    peak = max(map(abs,output))
    output = [x / peak * .62 for x in output]
    for i in range(int(RATE*.2)):
        output[-i-1] *= i / (RATE*.2)
    with wave.open(str(destination),'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(RATE)
        wav.writeframes(struct.pack('<'+'h'*len(output),*(round(x*32767) for x in output)))
    return max(map(abs,output)),math.sqrt(sum(x*x for x in output)/len(output))

if __name__ == '__main__':
    print(render(Path(__file__).with_name('brand-intro.wav')))
