"""Procesamiento de texto alrededor del traductor.

Antes de traducir:
  * `split_sentences`: los modelos MT a veces omiten una oración cuando reciben
    dos juntas ("Are you ready? Because…" → solo la segunda). Se traducen por
    separado.
  * `preedit`: reescribe modismos ingleses a su sentido literal; ningún modelo
    probado traduce bien "raining cats and dogs" o "call it a day".

Después:
  * `match_shape`: las frases de Whisper pueden ser fragmentos (cortadas por
    pausa o largo). Si el original empieza en minúscula o no termina en punto,
    la traducción tampoco.
  * `polish`: espacios, símbolos y convenciones del español latinoamericano.
"""

import re

_ABBR = "".join(rf"(?<!\b{a}\.)" for a in ("Mr", "Mrs", "Ms", "Dr", "St", "vs", "Jr", "Sr", "[A-Z]"))
_SPLIT = re.compile(r"(?<=[.!?…])" + _ABBR + r"[\"')\]]*\s+(?=[\"'(\[]?[A-Z0-9¿¡])")
_END = re.compile(r"[.!?…][\"')\]]*$")

# modismo → sentido literal (en inglés, antes de traducir). Ampliable.
IDIOMS: list[tuple[str, str]] = [
    (r"raining cats and dogs", "raining very heavily"),
    (r"call it a day", "stop for today"),
    (r"call it a night", "stop for tonight"),
    (r"(a )?piece of cake", "very easy"),
    (r"break a leg", "good luck"),
    (r"under the weather", "a little sick"),
    (r"hit the (sack|hay)", "go to bed"),
    (r"on the fence", "undecided"),
    (r"once in a blue moon", "very rarely"),
    (r"cost(s|ed)? an arm and a leg", r"cost\1 a fortune"),
    (r"spill(ed)? the beans", r"reveal\1 the secret"),
    (r"bite the bullet", "do it even though it is hard"),
    (r"the ball is in your court", "it is your decision now"),
    (r"beat around the bush", "avoid the main topic"),
    (r"(it'?s|that'?s) not rocket science", r"\1 not complicated"),
    (r"hang in there", "do not give up"),
    (r"no brainer", "obvious decision"),
    (r"(a )?game changer", "something that changes everything"),
    (r"low[- ]hanging fruit", "easiest opportunities"),
    (r"at the end of the day", "in the end"),
    (r"let'?s get (this|the) ball rolling", "let's start"),
    (r"let'?s dive in", "let's start"),
    (r"without further ado", "without more delay"),
    (r"smash (that|the) like button", "press the like button"),
    # giros que Opus-MT traduce literal (detectados con tools/eval_translation.py)
    (r"(totally|completely|definitely|so|absolutely) worth it", "really worth it"),
    (r"pretty much it", "all"),
    (r"let us know", "tell us"),
    (r"let me know", "tell me"),
    (r"count me in", "I'm in"),
    (r"would you go back", "would you return"),
    (r"want to go(?=[.!?,])", "want to go there"),
    (r"works out to", "is equivalent to"),
    (r"worked out to", "was equivalent to"),
    (r"(has|have|had) been out for", r"\1 been available for"),
    (r"(the code|what) it puts out", r"\1 it produces"),
    (r",? if I'?m being real", ", honestly"),
    (r"super legit", "very trustworthy"),
]
_IDIOMS = [(re.compile(r"\b" + p + r"\b", re.I), r) for p, r in IDIOMS]

# convenciones latinoamericanas sobre salidas típicas de Opus-MT (entrenado con
# mucho español peninsular)
_LATAM = [
    (re.compile(r"\bvídeo(s?)\b"), r"video\1"),
    (re.compile(r"\bVídeo(s?)\b"), r"Video\1"),
    (re.compile(r"\b([Vv])amos a por\b"), r"\1amos por"),
    (re.compile(r"\bordenador(es)?\b"), r"computadora\1"),
    (re.compile(r"\bmóvil(es)?\b"), r"celular\1"),
    (re.compile(r"\bcoche(s)?\b"), r"auto\1"),
    (re.compile(r"\b([Gg])racias por mirar\b"), r"\1racias por ver"),
    (re.compile(r"\bahí fuera\b"), "allá afuera"),
    (re.compile(r"\bes equivalente a\b"), "equivale a"),
    (re.compile(r"\bdar(le)? [\"“]?[Mm]e gusta[\"”]?"), r"dar\1 like"),
    # "vosotros" (España) → "ustedes"
    (re.compile(r"\b(habl|cont|mostr|enseñ|dej|pregunt|explic)aros\b"), r"\1arles"),
    (re.compile(r"\bos (voy|vamos|quiero|recomiendo|dejo|cuento|muestro|enseño)\b"), r"les \1"),
]


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SPLIT.split(text.strip())]
    return [p for p in parts if p]


def preedit(text: str) -> str:
    def sub(rx, rep, t):
        def f(m):
            out = m.expand(rep)
            return out[:1].upper() + out[1:] if m.group(0)[:1].isupper() else out
        return rx.sub(f, t)

    for rx, rep in _IDIOMS:
        text = sub(rx, rep, text)
    return text


def match_shape(src: str, es: str) -> str:
    src, es = src.strip(), es.strip()
    if not src or not es:
        return es
    head = src.split()[0]
    if src[0].islower() and es[0].isupper() and not (len(es) > 1 and es[1].isupper()):
        es = es[0].lower() + es[1:]
    elif src[0].isupper() and es[0].islower() and head not in ("iPhone", "iPad", "eBay"):
        es = es[0].upper() + es[1:]
    if not _END.search(src) and es.endswith(".") and not es.endswith("..."):
        es = es[:-1]
    # fragmento que continúa la frase anterior: ", which …" → "lo que …"
    if re.match(r"which\b", src) and re.match(r"que\b", es):
        es = "lo " + es
    if src.endswith(",") and not es.endswith(","):
        es = es.rstrip(".") + ","
    return es


def polish(es: str) -> str:
    es = re.sub(r"\s+", " ", es).strip()
    es = re.sub(r"\s+([,.;:!?%])", r"\1", es)
    es = re.sub(r"([¿¡])\s+", r"\1", es)
    es = re.sub(r"(US)?\$\s+(\d)", r"\1$\2", es)
    for rx, rep in _LATAM:
        es = rx.sub(rep, es)
    return es
