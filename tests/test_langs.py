"""Idiomas: registro, traductor por idioma, reglas de texto, detección y «solo transcribir»."""

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vt import langs  # noqa: E402
from vt.asr import Word  # noqa: E402
from vt.prefs import Prefs  # noqa: E402
from vt.store import Store  # noqa: E402
from vt.streaming import Detected, Segment, StreamingTranscriber  # noqa: E402
from vt.textproc import polish, preedit, split_sentences  # noqa: E402
from vt.translate import FALLBACK, Translators, route, supports  # noqa: E402
from vt.vad import SR  # noqa: E402


def test_registry():
    assert langs.TARGET in langs.TARGETS and set(langs.SOURCES) <= set(langs.LANGS)
    for code in langs.SOURCES:
        lg = langs.LANGS[code]
        assert lg.code == code and len(lg.iso3) == 3 and "_" in lg.nllb and lg.name
    assert langs.get("xx").code == langs.DEFAULT_SOURCE and langs.name("pt") == "portugués"


def test_routes_per_language():
    assert route("en") == "opus-big" and route("en", "base") == "opus-base"
    assert route("pt") == "opus-itc" and supports("opus-itc", "pt", "es")
    assert not supports("opus-big", "pt", "es")
    # sin ruta medida en el lab: el de respaldo, aunque otro modelo lo soporte
    assert route("fr") == FALLBACK and route("de") == FALLBACK and supports(FALLBACK, "de", "es")
    t = Translators("big", force="opus-base")
    assert t.name_for("en") == "opus-base" and t.name_for("pt") == "opus-itc"  # el forzado solo donde traduce
    assert Translators(force="none").name_for("pt") == "none"


def test_portuguese_text_rules():
    assert preedit("Ele pisou na bola feio.", "pt") == "Ele errou feio."
    assert preedit("Bora começar? Tá chovendo, né?", "pt") == "Vamos começar? Está chovendo, certo?"
    assert preedit("Hoje eu vou mostrar pra vocês.", "pt") == "Hoje eu vou mostrar para vocês."
    assert preedit("Custou os olhos da cara, mas valeu muito a pena.", "pt") == "Custou muito caro, mas valeu muito a pena."
    assert preedit("Valeu, galera!", "pt") == "Obrigado, pessoal!"
    assert preedit("Let's call it a day.", "pt") == "Let's call it a day."  # las reglas inglesas no se cruzan
    assert split_sentences("O Sr. Silva chegou. Ele saiu.", "pt") == ["O Sr. Silva chegou.", "Ele saiu."]
    assert split_sentences("Chegou. Às vezes não.", "pt") == ["Chegou.", "Às vezes não."]
    assert polish("Hoy os voy a enseñar el vídeo") == "Hoy les voy a enseñar el video"


class LangASR:
    """Detecta `lang` y transcribe una palabra por segundo de voz."""

    def __init__(self, lang="pt", prob=0.98):
        self.lang, self.prob, self.detects = lang, prob, 0

    def detect(self, audio):
        self.detects += 1
        return self.lang, self.prob

    def transcribe(self, audio, prompt=None, language=None):
        assert language == self.lang  # una vez detectado, se reconoce en ese idioma
        n = int(len(audio) / SR)
        return [Word(i + 0.1, i + 0.6, " olá." if i == n - 1 else " olá", 0.99) for i in range(n)]


def tone(seconds):
    t = np.arange(int(seconds * SR)) / SR
    return (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def run(st, audio):
    events = []
    for i in range(0, len(audio), 1600):
        st.feed(i / SR, audio[i:i + 1600])
        if st.ready():
            events += st.step()
    return events + st.flush()


def test_streaming_detects_language_first():
    asr = LangASR("pt")
    st = StreamingTranscriber(asr, language="")
    ev = run(st, np.concatenate([tone(5), np.zeros(SR, np.float32)]))
    det = [e for e in ev if isinstance(e, Detected)]
    assert len(det) == 1 and det[0].lang == "pt" and st.language == "pt" and asr.detects == 1
    first_seg = next(i for i, e in enumerate(ev) if isinstance(e, Segment))
    assert ev.index(det[0]) < first_seg  # el idioma llega antes que la primera frase


def test_streaming_waits_for_confidence():
    asr = LangASR("pt", prob=0.6)
    st = StreamingTranscriber(asr, language="")
    run(st, np.concatenate([tone(4), np.zeros(SR, np.float32)]))
    assert asr.detects > 1 and st.language == "pt"  # con poca confianza esperó más voz; al final decidió


def test_streaming_never_guesses_a_doubtful_language():
    """Ruido o una sala de espera: Whisper dice «inglés» con poca confianza. En vivo no se decide
    (todo se reconocería traducido): ni el tramo queda cubierto; lo decide la cola con el archivo."""
    asr = LangASR("en", prob=0.3)
    st = StreamingTranscriber(asr, language="")
    speech = np.concatenate([np.concatenate([tone(1.5), np.zeros(SR // 4, np.float32)]) for _ in range(23)])  # ~40 s de «voz»
    ev = run(st, np.concatenate([speech, np.zeros(SR, np.float32)]))
    assert st.language == "" and not [e for e in ev if isinstance(e, Detected)]
    assert st.final_t <= st.start_t and st.duration < 30  # el búfer no crece sin fin


def test_queue_confirms_a_live_detection(tmp_path):
    """Lo detectado en vivo se confirma con el archivo completo; si era otro idioma se rehace."""
    from vt.streaming import speech_samples, vote_language

    tr = Store(tmp_path).open("cap_aaaaaaaaaaaa")
    assert tr.set_detected("en", own="es", live=True, prob=0.72) and tr.lang_unconfirmed
    tr.add_segment(0, 1, "So I will finish you", "Así que te terminaré", "opus-big")
    assert tr.redetect("es") and tr.lang == "es" and not tr.segments and not tr.covered and not tr.lang_unconfirmed
    ok = Store(tmp_path).open("cap_bbbbbbbbbbbb")
    ok.set_detected("en", own="es", live=True, prob=0.9)
    assert not ok.redetect("en") and not ok.lang_unconfirmed  # confirmado: no se vuelve a revisar
    chosen = Store(tmp_path).open("cap_cccccccccccc")
    chosen.set_detected("en", own="es", live=True, prob=0.6)
    chosen.set_lang("pt")
    assert not chosen.lang_unconfirmed  # lo eligió la persona
    # votación: el inicio (música) dice inglés, el resto español
    assert vote_language([{"en": 0.5, "es": 0.3}, {"es": 0.95}, {"es": 0.9, "en": 0.05}])[0] == "es"
    assert len(speech_samples(np.concatenate([tone(60), tone(60), tone(60)]))) == 3


def test_mode_and_detection(tmp_path):
    tr = Store(tmp_path).open("yt_aaaaaaaaaaa")
    assert tr.detecting and not tr.translates
    assert tr.set_detected("pt", own="es") and tr.lang == "pt" and tr.translates and not tr.detecting
    tr.add_segment(0, 1, "Olá a todos", "Hola a todos", "opus-itc")
    assert tr.set_mode("transcribe") and tr.transcribe_only
    assert tr.segments[0]["translation"] == "Hola a todos"  # cambiar de modo no borra nada
    assert tr.stale("opus-itc") == []
    tr.set_mode("translate")
    tr.add_segment(2, 3, "Tchau", None, None)
    assert [s["text"] for s in tr.stale("opus-itc")] == ["Tchau"]

    own = Store(tmp_path).open("yt_bbbbbbbbbbb")
    own.set_detected("pt", own="pt")  # el idioma propio: solo se transcribe
    assert own.mode == "transcribe" and own.transcribe_only
    other = Store(tmp_path).open("yt_ccccccccccc")
    other.set_mode("translate")
    other.set_detected("pt", own="pt")  # la persona eligió traducir: se respeta
    assert other.translates

    unknown = Store(tmp_path).open("yt_ddddddddddd")
    unknown.set_detected("ja", own="es")  # un idioma que aún no se traduce: solo se transcribe
    assert unknown.lang == "ja" and unknown.transcribe_only
    assert not unknown.set_lang("ja")  # a mano solo se eligen los del registro


def test_legacy_transcripts_keep_working(tmp_path):
    (tmp_path / "yt_eeeeeeeeeee.json").write_text(json.dumps({
        "id": "yt_eeeeeeeeeee", "segments": [{"id": 1, "start": 0, "end": 1, "text": "Hi", "translation": "Hola",
                                              "tr_model": "opus-big"}], "covered": [[0, 1]], "next_id": 1}))
    tr = Store(tmp_path).open("yt_eeeeeeeeeee")
    assert tr.lang == "en" and tr.translates and not tr.detecting
    assert not tr.set_lang("en") and tr.segments  # volver a importar en inglés no borra nada


def test_prefs_migrate_original_subtitles(tmp_path):
    p = tmp_path / "prefs.json"
    p.write_text(json.dumps({"sub_en": False}))
    prefs = Prefs(p)
    assert prefs.values["sub_orig"] is False and prefs.values["transcribe_lang"] == "es"
    assert prefs.set("transcribe_lang", "pt") and not prefs.set("transcribe_lang", "xx")


def test_detection_does_not_override_or_guess(tmp_path):
    tr = Store(tmp_path).open("yt_fffffffffff")
    assert tr.set_detected("en", own="es")
    tr.add_segment(0, 1, "Hello", "Hola", "opus-big")
    assert not tr.set_detected("pt", own="es") and tr.lang == "en"  # otra detección no cambia lo decidido

    asr = LangASR("pt")
    st = StreamingTranscriber(asr, language="")
    run(st, np.concatenate([tone(0.6), np.zeros(SR, np.float32)]))  # casi sin voz y se cierra
    assert st.language == "" and asr.detects == 0 and st.final_t == 0  # no adivina ni da el tramo por cubierto


def test_transcribe_only_app_mode(tmp_path):
    """Ajustes › Uso › «Transcribir y resumir»: nada se traduce ni se dobla, lo nuevo queda para solo
    transcribir (al volver a traducir no se pone a traducir de golpe) y lo ya elegido se conserva."""
    from vt import store as store_mod

    prefs = Prefs(tmp_path / "prefs.json")
    assert prefs.translating and prefs.set("app_mode", "transcribir") and not prefs.translating
    keys = {p["key"]: p for p in prefs.public()["schema"]}
    assert keys["audio"]["only"] == "traducir" and keys["sub_orig"]["alt"]["label"] == "Subtítulos"
    assert "add_button" not in keys
    old = store_mod.TRANSLATION
    try:
        store_mod.TRANSLATION = lambda: prefs.translating
        chosen = Store(tmp_path).open("yt_ggggggggggg")
        chosen.set_mode("translate")
        chosen.set_detected("en", own="es")
        assert not chosen.translates and chosen.mode == "translate"  # lo elegido queda para cuando se vuelva
        new = Store(tmp_path).open("yt_hhhhhhhhhhh")
        new.set_detected("en", own="es")
        assert new.mode == "transcribe" and not new.translates
        prefs.set("app_mode", "traducir")
        assert chosen.translates and not new.translates
    finally:
        store_mod.TRANSLATION = old
