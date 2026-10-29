"""Original warm felt-mallet and airy resonance studio signature; no samples."""
import math
from pathlib import Path
import struct
import wave

RATE = 44100
DURATION = 3.2


def render(destination):
    output = [0.0] * int(RATE * DURATION)
    # Open fifth, then octave: unhurried, with rounded attacks and few overtones.
    for start, frequency, level in [(0.10,329.628,.72),(.43,493.883,.50),(.82,659.255,.42)]:
        for i in range(int(RATE * 2.3)):
            t = i / RATE
            attack = (1 - math.exp(-t / .018)) ** 2
            value = sum(strength * math.sin(2*math.pi*frequency*ratio*t)
                        * math.exp(-t/decay)
                        for ratio,strength,decay in [(1,1,.72),(2,.10,.36),(3,.018,.20)])
            value *= attack * level
            for delay, gain in [(0,1),(.097,.085),(.173,.055),(.283,.035),(.419,.018)]:
                index = int((start+delay)*RATE)+i
                if index < len(output):
                    output[index] += value * gain
    # A quiet, smoothly fading low resonance adds depth without a bass impact.
    for i in range(len(output)):
        t = i/RATE
        envelope = (1-math.exp(-t/.26)) * math.exp(-t/.82)
        output[i] += .065*envelope*(math.sin(2*math.pi*164.814*t)+.35*math.sin(2*math.pi*246.942*t))
    peak = max(map(abs,output))
    output = [x/peak*.43 for x in output]
    fade = int(RATE*.45)
    for i in range(fade):
        output[-i-1] *= .5-.5*math.cos(math.pi*i/fade)
    with wave.open(str(destination),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(RATE)
        wav.writeframes(struct.pack('<'+'h'*len(output),*(round(x*32767) for x in output)))
    return max(map(abs,output)),math.sqrt(sum(x*x for x in output)/len(output))


if __name__ == '__main__':
    print(render(Path(__file__).with_name('brand-intro.wav')))
