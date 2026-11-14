"""Acciones del agente: pedidos que no necesitan al modelo y que la app resuelve al instante (también con el
agente apagado), cada uno con su tarjeta en la conversación.

    exportar   «exporta esto para Claude», «send it to ChatGPT»      → tarjeta con el video en Markdown (copiar, .md)
    ir a       «llévame al minuto 3:15», «go to where he explains X» → salta ahí; tarjeta con el momento
    subtítulos «pon los subtítulos en inglés», «tira as legendas»
    guardar    «guarda este video en Python», «save this to Python»  → lo agrega a esa colección
    avisos     «avísame cuando hablen de precios»                    → marca esos momentos y avisa al llegar

Las frases de cada idioma están en PHRASES (una entrada por idioma de vt/langs.py, con sus expresiones y sus
respuestas). Se reconoce el pedido en cualquier idioma, empezando por el de la app, y se responde en el de la
app. Agregar un idioma es agregar su entrada.

route() devuelve {text, card?, action?} o None (entonces responde el modelo, vt/agentsvc.py). La tarjeta y la
acción viajan con el mensaje (agent_done) y se guardan en la conversación; la acción la ejecuta la vista.
"""

from __future__ import annotations

import re

from . import agent, langs
from .videocontext import markdown, stamp

_I = re.I
_IS = re.I | re.S
_AGENTS = r"(claude|chat\s?gpt|gpt|gemini|copilot|notion|obsidian|markdown|md)"
_TARGETS = {"claude": "Claude", "chatgpt": "ChatGPT", "chat gpt": "ChatGPT", "gpt": "ChatGPT", "gemini": "Gemini",
            "copilot": "Copilot", "notion": "Notion", "obsidian": "Obsidian"}
_CLOCK = re.compile(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b")

PHRASES = {
    "es": {
        "export": re.compile(r"\b(export\w*|p[aá]s\w*|ll[eé]v\w*|c[oó]pi\w*|m[aá]nd\w*|env[ií]\w*|s[aá]c\w*|prep[aá]r\w*)\b.*"
                             rf"\b({_AGENTS[1:-1]}|un agente|otro agente|agente|ia)\b", _IS),
        "export_for": re.compile(r"\bpara\s+(claude|chat\s?gpt|gemini|copilot|notion|obsidian)\b", _I),
        "seek": re.compile(r"^\s*(ll[eé]vame|ve\b|vamos|ir\b|salta|p[oó]nlo|pon el video|reproduce|repite|regresa|vuelve|"
                           r"mu[eé]strame (el|la) (momento|parte))", _I),
        "seek_lead": re.compile(r"^(a|al|hasta|donde|la parte|el momento|en que|en qué|cuando)\s+", _I),
        "minute": re.compile(r"\bminuto\s+(\d{1,3})(?:\s*(?:y|con)\s*(\d{1,2})\s*segundos?)?\b", _I),
        "subs": re.compile(r"\bsubt[ií]tulos?\b", _I),
        "subs_on": re.compile(r"\b(pon|activa|muestra|cambia|quita|apaga|oculta|desactiva|sin)\b", _I),
        "subs_off": re.compile(r"\b(quita|apaga|oculta|desactiva|sin)\b", _I),
        "orig": re.compile(r"\b(ingl[eé]s|portugu[eé]s|original|english)\b", _I),
        "save": re.compile(r"^\s*(guarda|gu[aá]rdalo|agrega|agr[eé]galo|a[nñ]ade|a[nñ][aá]delo|mete|m[eé]telo)\b(?:\s+(?:este|el)\s+video)?"
                           r"\s+(?:en|a)\s+(?:la\s+colecci[oó]n\s+|mi\s+colecci[oó]n\s+)?[«\"']?(.+?)[»\"']?\s*\.?\s*$", _I),
        "alert": re.compile(r"\b(av[ií]same|avisa|al[eé]rtame|marca|m[aá]rcame|notif[ií]came)\b.*?\b(cuando|donde|si|en qu[eé])\b\s*"
                            r"(?:se\s+)?(?:hablen|habla|hable|digan|dice|diga|mencionen|menciona|mencione|aparezca|aparece|expliquen|"
                            r"explica|explique|toquen|toca|trate|tratan|trata)?\s*(?:de|del|sobre|acerca de|la|el|los|las)?\s*(.+?)\s*\.?\s*$", _IS),
        "topic_lead": re.compile(r"^(de|del|sobre)\s+", _I),
        "say": {
            "export_title": "Para pegar en {target}", "export_title_any": "Para pegar en un agente",
            "export": "Listo: el video completo en Markdown, con sus tiempos, la traducción y lo que aparece en pantalla{extra}.",
            "export_extra": ", listo para {target}",
            "alert_none": "No encontré momentos donde se hable de «{topic}» en este video.",
            "alert_one": "Te aviso al llegar al momento donde se habla de «{topic}». Lo marqué en la barra de avance.",
            "alert_many": "Te aviso al llegar a los {n} momentos donde se habla de «{topic}». Los marqué en la barra de avance.",
            "subs_off": "Listo: subtítulos desactivados.", "subs": "Listo: subtítulos en {lang}.",
            "save": "Lo guardo en «{name}».", "seek": "Vamos a [{t}].", "seek_topic": "Vamos a [{t}], donde se habla de eso.",
        },
    },
    "en": {
        "export": re.compile(r"\b(export\w*|send\w*|cop(y|ies)\w*|pass\w*|take\w*|prepar\w*|move\w*|share\w*)\b.*"
                             rf"\b({_AGENTS[1:-1]}|an agent|another agent|agent|ai)\b", _IS),
        "export_for": re.compile(r"\bfor\s+(claude|chat\s?gpt|gemini|copilot|notion|obsidian)\b", _I),
        "seek": re.compile(r"^\s*(take me|go\b|jump|skip|play from|replay|rewind|back to|show me the (moment|part))", _I),
        "seek_lead": re.compile(r"^(to|back to|the part|the moment|where|when|in which)\s+", _I),
        "minute": re.compile(r"\bminute\s+(\d{1,3})(?:\s*(?:and)\s*(\d{1,2})\s*seconds?)?\b", _I),
        "subs": re.compile(r"\b(subtitles?|captions?|subs)\b", _I),
        "subs_on": re.compile(r"\b(turn|put|show|switch|change|enable|hide|remove|disable|no)\b", _I),
        "subs_off": re.compile(r"\b(off|hide|remove|disable|no)\b", _I),
        "orig": re.compile(r"\b(original|english|portuguese|source)\b", _I),
        "save": re.compile(r"^\s*(save|add|put|file)\b(?:\s+(?:this|the)(?:\s+video)?|\s+it)?\s+(?:in|to|into)\s+"
                           r"(?:the\s+collection\s+|my\s+collection\s+)?[«\"']?(.+?)[»\"']?\s*\.?\s*$", _I),
        "alert": re.compile(r"\b(tell me|let me know|alert me|notify me|warn me|mark|ping me)\b.*?\b(when|where|if)\b\s*"
                            r"(?:they|he|she|it|someone)?\s*(?:talks?|talk|speaks?|mentions?|mention|explains?|explain|covers?|"
                            r"discuss(?:es)?|gets? to|appears?)?\s*(?:about|on|of|the)?\s*(.+?)\s*\.?\s*$", _IS),
        "topic_lead": re.compile(r"^(about|on|of)\s+", _I),
        "say": {
            "export_title": "To paste into {target}", "export_title_any": "To paste into an agent",
            "export": "Done: the whole video in Markdown, with its times, the translation and what appears on screen{extra}.",
            "export_extra": ", ready for {target}",
            "alert_none": "I couldn't find moments where \"{topic}\" comes up in this video.",
            "alert_one": "I'll let you know when you reach the moment where \"{topic}\" comes up. I marked it on the progress bar.",
            "alert_many": "I'll let you know when you reach the {n} moments where \"{topic}\" comes up. I marked them on the progress bar.",
            "subs_off": "Done: subtitles off.", "subs": "Done: subtitles in {lang}.",
            "save": "Saving it to \"{name}\".", "seek": "Going to [{t}].", "seek_topic": "Going to [{t}], where that comes up.",
        },
    },
    "pt": {
        "export": re.compile(r"\b(export\w*|pass\w*|lev\w*|copi\w*|mand\w*|envi\w*|prepar\w*|compartilh\w*)\b.*"
                             rf"\b({_AGENTS[1:-1]}|um agente|outro agente|agente|ia)\b", _IS),
        "export_for": re.compile(r"\bpara\s+o?\s*(claude|chat\s?gpt|gemini|copilot|notion|obsidian)\b", _I),
        "seek": re.compile(r"^\s*(me leva|leva|vai\b|vá\b|ir\b|pula|pule|volta|volte|repete|repita|toca a partir|"
                           r"mostra (o|a) (momento|parte)|me mostra (o|a) (momento|parte))", _I),
        "seek_lead": re.compile(r"^(para|pro|pra|até|ao|a parte|o momento|onde|quando|em que)\s+", _I),
        "minute": re.compile(r"\bminuto\s+(\d{1,3})(?:\s*(?:e)\s*(\d{1,2})\s*segundos?)?\b", _I),
        "subs": re.compile(r"\blegendas?\b", _I),
        "subs_on": re.compile(r"\b(p[oõ]e|coloca|ativa|mostra|muda|troca|tira|desliga|esconde|desativa|sem)\b", _I),
        "subs_off": re.compile(r"\b(tira|desliga|esconde|desativa|sem)\b", _I),
        "orig": re.compile(r"\b(ingl[eê]s|espanhol|original|english)\b", _I),
        "save": re.compile(r"^\s*(salva|salve|guarda|guarde|adiciona|adicione|coloca|coloque|p[oõ]e)\b(?:\s+(?:este|esse|o)\s+v[ií]deo|\s+isso|\s+isto)?"
                           r"\s+(?:em|na|no|a)\s+(?:cole[cç][aã]o\s+|minha\s+cole[cç][aã]o\s+)?[«\"']?(.+?)[»\"']?\s*\.?\s*$", _I),
        "alert": re.compile(r"\b(me avisa|avise-me|avisa|me alerta|marca|me notifica)\b.*?\b(quando|onde|se)\b\s*"
                            r"(?:se\s+)?(?:falarem|falar|fala|mencionarem|mencionar|menciona|aparecer|aparece|explicarem|explicar|"
                            r"explica|tratar|trata)?\s*(?:de|do|da|dos|das|sobre|o|a|os|as)?\s*(.+?)\s*\.?\s*$", _IS),
        "topic_lead": re.compile(r"^(de|do|da|sobre)\s+", _I),
        "say": {
            "export_title": "Para colar no {target}", "export_title_any": "Para colar em um agente",
            "export": "Pronto: o vídeo inteiro em Markdown, com os horários, a tradução e o que aparece na tela{extra}.",
            "export_extra": ", pronto para o {target}",
            "alert_none": "Não encontrei momentos em que se fale de «{topic}» neste vídeo.",
            "alert_one": "Te aviso quando chegar ao momento em que se fala de «{topic}». Marquei na barra de progresso.",
            "alert_many": "Te aviso quando chegar aos {n} momentos em que se fala de «{topic}». Marquei na barra de progresso.",
            "subs_off": "Pronto: legendas desativadas.", "subs": "Pronto: legendas em {lang}.",
            "save": "Vou salvar em «{name}».", "seek": "Vamos para [{t}].", "seek_topic": "Vamos para [{t}], onde se fala disso.",
        },
    },
}


def _parts(tr) -> list[dict]:
    """Cada frase como fragmento para buscar (original + traducción)."""
    return [{"start": s["start"], "end": s["end"], "text": f"{s.get('text', '')} {s.get('translation') or ''}",
             "es": (s.get("translation") or s.get("text") or "").strip()} for s in tr.segments]


def _when(question: str, P: dict | None = None) -> float | None:
    # primero una hora escrita (1:35); si no, «minuto 3» en cualquier idioma
    hm = _CLOCK.search(question)
    if hm:
        a, b, c = hm.groups()
        return int(a) * 3600 + int(b) * 60 + int(c) if c else int(a) * 60 + int(b)
    for p in ([P] if P else []) + list(PHRASES.values()):
        m = p["minute"].search(question)
        if m:
            mins, secs = m.groups()
            return int(mins) * 60 + int(secs or 0)
    return None


def _order(ui: str) -> list[dict]:
    """Las tablas a probar: primero la del idioma de la app."""
    return [PHRASES[ui]] + [p for k, p in PHRASES.items() if k != ui]


def route(question: str, info: dict, tr, screen: dict | None, position: float | None, ui: str | None = None) -> dict | None:
    q = question.strip()
    if not q:
        return None
    ui = ui if ui in PHRASES else (langs.ui() if langs.ui() in PHRASES else "es")
    say = PHRASES[ui]["say"]
    tables = _order(ui)

    # exportar el video para otro agente
    if any(P["export_for"].search(q) or (P["export"].search(q) if len(q) < 160 else None) for P in tables):
        target = next((name for key, name in _TARGETS.items() if re.search(rf"\b{key}\b", q, re.I)), "")
        content = markdown(info, tr, screen, position, ui=ui)
        title = say["export_title"].format(target=target) if target else say["export_title_any"]
        return {"text": say["export"].format(extra=say["export_extra"].format(target=target) if target else ""),
                "card": {"type": "export", "title": title, "target": target, "content": content,
                         "file": re.sub(r"[^\w-]+", "-", (info.get("title") or tr.data.get("name") or "video").strip())[:60] + ".md"}}

    # avisos mientras ves
    for P in tables:
        m = P["alert"].search(q)
        if m and m.group(3).strip():
            topic = P["topic_lead"].sub("", m.group(3).strip())
            hits = agent.search(_parts(tr), topic, k=8)
            times = [{"t": round(h["start"], 2), "text": h["es"][:160]} for h in hits]
            if not times:
                return {"text": say["alert_none"].format(topic=topic)}
            text = say["alert_one"] if len(times) == 1 else say["alert_many"]
            return {"text": text.format(topic=topic, n=len(times)),
                    "card": {"type": "alert", "topic": topic, "times": times},
                    "action": {"type": "alert", "topic": topic, "times": times}}

    # subtítulos («en» = los del idioma original, «es» = los traducidos: nombres de siempre de la vista)
    for P in tables:
        if P["subs"].search(q) and P["subs_on"].search(q):
            if P["subs_off"].search(q):
                return {"text": say["subs_off"], "action": {"type": "subs", "value": "off"}}
            orig = bool(P["orig"].search(q))
            name = langs.name(tr.lang if orig else tr.target, ui)
            return {"text": say["subs"].format(lang=name), "action": {"type": "subs", "value": "en" if orig else "es"}}

    # guardar en una colección
    for P in tables:
        m = P["save"].search(q)
        if m and len(m.group(2)) <= 60:
            name = m.group(2).strip(" .»\"'")
            return {"text": say["save"].format(name=name), "action": {"type": "save", "collection": name}}

    # ir a un momento
    for P in tables:
        if not P["seek"].search(q):
            continue
        t = _when(q, P)
        if t is not None:
            seg = min(tr.segments, key=lambda s: abs(s["start"] - t), default=None)
            text = ((seg.get("translation") or seg.get("text") or "").strip() if seg else "")[:180]
            return {"text": say["seek"].format(t=stamp(t)), "card": {"type": "moment", "t": t, "text": text},
                    "action": {"type": "seek", "t": t}}
        topic = P["seek_lead"].sub("", P["seek"].sub("", q).strip())
        hit = agent.search(_parts(tr), topic, k=1)
        if hit:
            h = hit[0]
            return {"text": say["seek_topic"].format(t=stamp(h["start"])),
                    "card": {"type": "moment", "t": round(h["start"], 2), "text": h["es"][:180]},
                    "action": {"type": "seek", "t": round(h["start"], 2)}}
        return None
    return None
