"""Compara traductores EN→ES sobre frases típicas de video (salida tipo Whisper).

Imprime la traducción de cada modelo lado a lado y su latencia por frase
(una frase a la vez, como en vivo). La calidad se juzga leyendo; la tabla
final resume velocidad y memoria.

    python tools/eval_translation.py --models opus-base opus-big nllb-1.3b madlad-3b
"""

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vt.translate import CT2Translator  # noqa: E402

SENTENCES = [
    # tutorial / explicativo
    "Welcome to this short demonstration.",
    "First, the audio is split into small frames, and each frame is analyzed to detect whether someone is speaking.",
    "Then, a neural network converts the sound into words.",
    "Make sure you save your work before you close the app.",
    "If you run into any issues, just restart the server and try again.",
    "Click on the settings icon in the top right corner.",
    # conversacional / vlog
    "Hey guys, what's up? Welcome back to the channel.",
    "I'm gonna be honest with you, I wasn't expecting that at all.",
    "So yeah, that's pretty much it for today.",
    "Don't forget to like and subscribe if you enjoyed this video.",
    "We ended up getting stuck in traffic for like two hours.",
    "You know what, let's just go for it.",
    # modismos y verbos frasales
    "It's raining cats and dogs out there.",
    "She finally figured out how to get away with it.",
    "Let's call it a day.",
    "That movie was a total rip-off.",
    "He's been looking forward to this trip for months.",
    # entrevistas / formal
    "The company reported a fifteen percent increase in revenue during the third quarter.",
    "I think the biggest challenge we face right now is climate change.",
    "When I was growing up, my parents always told me to follow my dreams.",
    "Can you tell us a little bit about how you got started?",
    # nombres, cifras, siglas
    "Elon Musk announced that SpaceX will launch the new rocket on March 3rd.",
    "The iPhone 15 costs about $799 in the United States.",
    "NASA's James Webb telescope captured images of galaxies 13 billion light years away.",
    # fragmentos de ASR (sin puntuación, cortados)
    "and then we went to the store and bought some",
    "Finally, in a future version,",
    "the text will be translated into Spanish and spoken with a natural voice",
    "you know I mean it's not like",
    # pronombres / género / tú-usted
    "Thank you for watching, and see you in the next episode.",
    "Are you ready? Because this is going to be fun.",
    "My sister is a doctor and she works at the hospital downtown.",
    "The teacher told the students that they were late.",
    # casos difíciles detectados en samples/dialogue.mp4
    "The cabin was amazing, and the view was totally worth it.",
    "How much did it cost?",
    "Before we move on, don't forget to like and subscribe if you enjoyed this video.",
    "And let us know in the comments where we should go next.",
    "All right, I think that's pretty much it for today.",
    "It was.",
    "Today we have a really fun episode for you.",
]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--models", nargs="+", default=["opus-base", "opus-big", "nllb-1.3b", "madlad-3b"])
    p.add_argument("--compute-type", default=None)
    p.add_argument("--beam", type=int, default=4)
    p.add_argument("--only", type=int, default=0, help="solo las últimas N frases")
    a = p.parse_args()
    global SENTENCES
    if a.only:
        SENTENCES = SENTENCES[-a.only:]

    results, stats = {}, {}
    for name in a.models:
        t = time.perf_counter()
        tr = CT2Translator(name, compute_type=a.compute_type, beam_size=a.beam)
        load = time.perf_counter() - t
        tr.translate("Warm up.")
        lat, out = [], []
        for s in SENTENCES:
            t = time.perf_counter()
            out.append(tr.translate(s))
            lat.append((time.perf_counter() - t) * 1000)
        results[name] = out
        stats[name] = (load, statistics.median(lat), max(lat))
        del tr

    for i, s in enumerate(SENTENCES):
        print(f"\n[{i:02}] {s}")
        for name in a.models:
            print(f"   {name:<16} {results[name][i]}")
    print("\nmodelo      carga   mediana   máx")
    for name, (load, med, mx) in stats.items():
        print(f"{name:<10} {load:5.1f}s  {med:6.0f}ms  {mx:5.0f}ms")


if __name__ == "__main__":
    main()
