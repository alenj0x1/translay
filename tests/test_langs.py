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
from vt.textproc import match_shape, polish, preedit, split_sentences  # noqa: E402
from vt.translate import FALLBACK, Translators, route, supports  # noqa: E402
from vt.vad import SR  # noqa: E402


def test_registry():
    assert langs.target() in langs.TARGETS and set(langs.SOURCES) <= set(langs.LANGS)
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


def test_italian():
    assert langs.is_source("it") and langs.name("it") == "italiano" and langs.name("it", "en") == "Italian"
    assert route("it") == "opus-itc" and route("it", tgt="pt") == "opus-itc" and route("it", tgt="en") == "opus-roa-en"
    assert route("it", "base") == "opus-itc"
    assert split_sentences("Il Sig. Rossi è arrivato. Il Dott. Bianchi no.", "it") == [
        "Il Sig. Rossi è arrivato.", "Il Dott. Bianchi no."]
    assert preedit("Costa un occhio della testa, ma ne vale la pena.", "it") == "Costa moltissimo, ma ne vale la pena."
    assert split_sentences("È arrivato. È andato via.", "it") == ["È arrivato.", "È andato via."]
    # créditos de subtítulos que Whisper inventa sobre silencio, normalizados como en el streaming
    from vt.streaming import HALLUCINATIONS, _norm
    for said in ("Sottotitoli creati dalla comunità Amara.org", "Sottotitoli a cura di QTSS",
                 "Sottotitoli e revisione a cura di QTSS"):
        words = [Word(i, i + 1, " " + w) for i, w in enumerate(said.split())]
        assert " ".join(_norm(w) for w in words) in HALLUCINATIONS["it"]


def test_japanese_text_rules():
    assert langs.is_source("ja") and langs.name("ja") == "japonés" and langs.name("ja", "en") == "Japanese"
    # sin espacios ni mayúsculas: se corta tras 。！？, con la comilla de cierre, sin cortar una cita que sigue
    assert split_sentences("こんにちは。今日はサーバーを設定します！準備はいいですか？はい", "ja") == [
        "こんにちは。", "今日はサーバーを設定します！", "準備はいいですか？", "はい"]
    assert split_sentences("彼は「すごい！」と言った。次に行きます。", "ja") == ["彼は「すごい！」と言った。", "次に行きます。"]
    assert split_sentences("「本当？」「うん。」それでいい。", "ja") == ["「本当？」", "「うん。」", "それでいい。"]
    assert split_sentences("バージョン3.5です。", "ja") == ["バージョン3.5です。"]
    # la traducción conserva su punto cuando el original japonés termina en 。
    assert match_shape("今日はサーバーを設定します。", "Hoy configuro el servidor.") == "Hoy configuro el servidor."
    assert match_shape("「すごい！」", "¡Increíble!") == "¡Increíble!"
    # un fragmento (sin 。) no lo lleva; uno que termina en 、 sigue con coma
    assert match_shape("今日はサーバーを", "Hoy el servidor.") == "Hoy el servidor"
    assert match_shape("まず、", "Primero.") == "Primero,"
    # sin mayúsculas en el original: la de la traducción no se toca
    assert match_shape("iPhoneは高いです。", "El iPhone es caro.") == "El iPhone es caro."


def test_korean_text_rules():
    assert langs.is_source("ko") and langs.name("ko") == "coreano" and langs.name("ko", "pt") == "coreano"
    # el hangul no tiene mayúsculas: basta el punto y el espacio
    assert split_sentences("안녕하세요. 오늘은 서버를 설정합니다! 준비됐나요? 네", "ko") == [
        "안녕하세요.", "오늘은 서버를 설정합니다!", "준비됐나요?", "네"]
    assert split_sentences("Mr. Kim이 왔어요. 버전 3.5예요.", "ko") == ["Mr. Kim이 왔어요.", "버전 3.5예요."]
    assert match_shape("오늘은 서버를 설정합니다.", "hoy configuro el servidor.") == "hoy configuro el servidor."
    assert match_shape("오늘은 서버를", "Hoy el servidor.") == "Hoy el servidor"


def test_japanese_and_korean_routes_download_on_demand():
    from vt import modelset
    from vt.translate import MODELS
    for src in ("ja", "ko"):
        for tgt in ("es", "pt", "en"):
            assert route(src, tgt=tgt) == "madlad-3b" and route(src, "base", tgt=tgt) == "madlad-3b"
    # MADLAD (~3 GB) no se baja con el perfil, sino con el primer video en japonés o coreano
    madlad = MODELS["madlad-3b"][1]
    for profile in ("calidad", "ligero", "texto"):
        assert madlad not in modelset.repos(profile) and modelset.on_demand(profile) == [madlad]


def test_summary_counts_japanese_without_spaces():
    from vt.summarize import words
    assert words("one two three four five") == 7  # inglés: como antes
    assert words("今日はサーバーを設定します。") == 14  # sin espacios: un token por carácter (y el 。), no «1 palabra»
    assert words("오늘은 서버를 설정합니다") == 11


def test_cased_languages_keep_their_rules():
    """Las reglas de japonés y coreano no cambian las de inglés, español y portugués."""
    assert split_sentences("Hello there. how are you? Fine.", "en") == ["Hello there. how are you?", "Fine."]
    assert split_sentences("Hola. ¿Cómo están? Bien.", "es") == ["Hola.", "¿Cómo están?", "Bien."]
    assert split_sentences("O Sr. Silva chegou. ele saiu.", "pt") == ["O Sr. Silva chegou. ele saiu."]
    assert match_shape("the text will be", "El texto será.") == "el texto será"
    assert match_shape("Hello.", "hola.") == "Hola."
    assert match_shape("Finally, in a version,", "Finalmente, en una versión.") == "Finalmente, en una versión,"


class ScriptASR:
    """Devuelve las palabras de un guion (inicio, fin, texto) cuyo audio ya está en el búfer."""

    def __init__(self, script):
        self.script, self.st = script, None

    def transcribe(self, audio, prompt=None, language=None):
        t0 = self.st.t0
        end = t0 + len(audio) / SR
        return [Word(a - t0, b - t0, w, 0.99) for a, b, w in self.script if b <= end and a >= t0 - 0.01]


def _segments(lang, script, speech_s):
    asr = ScriptASR(script)
    st = StreamingTranscriber(asr, language=lang)
    asr.st = st
    return [e.text for e in run(st, np.concatenate([tone(speech_s), np.zeros(int(1.5 * SR), np.float32)]))
            if isinstance(e, Segment)]


def test_streaming_japanese_pause_closes_with_its_period():
    # faster-whisper parte el japonés en trozos de caracteres, sin espacios
    pieces = ["今日", "は", "サーバー", "を", "設定", "します"]
    script = [(0.2 + 0.3 * i, 0.45 + 0.3 * i, w) for i, w in enumerate(pieces)]
    assert _segments("ja", script, 2.1) == ["今日はサーバーを設定します。"]  # 。, no «.»
    done = script[:-1] + [(script[-1][0], script[-1][1], "します。")]
    assert _segments("ja", done, 2.1) == ["今日はサーバーを設定します。"]  # ya cerrada: sin otro punto
    # seis trozos y menos de 5 caracteres: no es una oración (como «3 palabras» en inglés)
    short = [(0.2, 0.4, "は"), (0.4, 0.6, "い"), (0.6, 0.8, "、"), (0.8, 1.0, "そう")]
    assert _segments("ja", short, 1.1) == ["はい、そう"]


def test_japanese_and_korean_hallucinations_are_dropped():
    """Lo que Whisper escribió sobre audio sin voz (tools/lab/langs_silence.py), con la clave como en
    el streaming: el japonés llega en trozos y se une sin espacios."""
    from vt.streaming import HALLUCINATIONS

    def emitted(lang, pieces, prob):
        st = StreamingTranscriber(None, language=lang)
        st.feed(0.0, np.zeros(4 * SR, np.float32))
        words = [Word(0.2 + 0.3 * i, 0.45 + 0.3 * i, w, prob) for i, w in enumerate(pieces)]
        return [s.text for s in st._emit(words)]

    ja = ["ご", "視聴", "ありがとう", "ございました", "。"]
    assert emitted("ja", ja, 0.6) == []
    assert emitted("ja", ja, 0.95) == ["ご視聴ありがとうございました。"]  # dicho con seguridad: se queda
    assert emitted("ko", [" 다음", " 영상에서", " 만나요."], 0.6) == []
    assert "시청해 주셔서 감사합니다" in HALLUCINATIONS["ko"] and "ご視聴ありがとうございました" in HALLUCINATIONS["ja"]
    # créditos con variantes y bucles (escrito sobre la música de un video de TWICE)
    loop = [" 한글자막", " 제공", " 및", " 자막", " 제공", " 및", " 자막", " 제공", " 및"]
    assert emitted("ko", loop, 0.6) == []
    assert emitted("ko", [" 한글자막", " 제공:", " 누군가"], 0.6) == []
    assert emitted("en", [" I", " said", " no,", " no,", " no"], 0.6) != []  # una palabra repetida es habla
    assert emitted("ko", [" 안녕하세요,", " 여러분들."], 0.6) != []


def test_streaming_korean_and_english_pause_close_with_a_dot():
    ko = [(0.2, 0.6, " 오늘은"), (0.7, 1.1, " 서버를"), (1.2, 1.7, " 설정합니다")]
    assert _segments("ko", ko, 1.8) == ["오늘은 서버를 설정합니다."]
    en = [(0.2, 0.6, " hello"), (0.7, 1.1, " my"), (1.2, 1.7, " friend")]
    assert _segments("en", en, 1.8) == ["Hello my friend."]
    assert _segments("en", en[:2], 1.2) == ["Hello my"]  # dos palabras: sin punto, como antes


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
    unknown.set_detected("zh", own="es")  # un idioma que aún no se traduce: solo se transcribe
    assert unknown.lang == "zh" and unknown.transcribe_only
    assert not unknown.set_lang("zh")  # a mano solo se eligen los del registro


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
    assert prefs.values["sub_orig"] is False and prefs.values["transcribe_lang"] == ""
    assert prefs.set("transcribe_lang", "pt") and not prefs.set("transcribe_lang", "xx")
    assert prefs.values["language"] == "es" and prefs.target == "es"  # de antes de los idiomas: español


def test_language_choice_and_target(tmp_path, monkeypatch):
    monkeypatch.setattr("vt.langs.system", lambda: "pt")
    prefs = Prefs(tmp_path / "prefs.json")  # instalación nueva: el idioma del sistema
    assert prefs.ui_lang == "pt" and prefs.target == "pt"
    seen = []
    prefs.listeners.append(lambda k, v: seen.append((k, v)))
    assert prefs.set("language", "en") and prefs.target == "en"
    assert prefs.set("target_lang", "es") and prefs.ui_lang == "en" and prefs.target == "es"
    assert seen == [("language", "en"), ("target_lang", "es")]
    assert not prefs.set("language", "fr")


def test_translation_per_target_language(tmp_path):
    from vt import langs
    (tmp_path / "yt_ggggggggggg.json").write_text(json.dumps({
        "id": "yt_ggggggggggg", "lang": "en", "next_id": 1, "covered": [[0, 1]],
        "segments": [{"id": 1, "start": 0, "end": 1, "text": "Hi", "translation": "Hola", "tr_model": "opus-big",
                      "dub": {"file": "yt_ggggggggggg/1.wav", "text": "Hola"}}]}))
    tr = Store(tmp_path).open("yt_ggggggggggg")
    assert tr.target == "es" and tr.translates
    assert tr.use_target("pt")
    seg = tr.segments[0]
    assert seg["translation"] is None and "dub" not in seg and tr.stale("opus-big-en-pt") == [seg]
    assert "alt" not in tr.public()["segments"][0] and tr.public()["target"] == "pt"
    tr.set_translation(1, "Olá", "opus-big-en-pt")
    assert tr.use_target("es")
    assert seg["translation"] == "Hola" and seg["dub"]["file"].endswith("1.wav") and seg["alt"]["pt"]["translation"] == "Olá"
    assert tr.use_target("pt") and seg["translation"] == "Olá"
    assert not tr.use_target("pt") and not tr.use_target("fr")
    assert langs.target() == "es"


def test_video_in_target_language_is_only_transcribed(tmp_path):
    tr = Store(tmp_path).open("yt_hhhhhhhhhhh")
    tr.set_lang("en")
    assert tr.translates
    tr.use_target("en")
    assert tr.mode == "transcribe" and not tr.translates


def test_routes_cover_every_pair():
    from vt import langs
    from vt.translate import FALLBACK, ROUTES, route, supports
    for a in langs.SOURCES:
        for b in langs.TARGETS:
            if a != b:
                assert (a, b) in ROUTES, (a, b)
                for tier in ("big", "base"):
                    name = route(a, tier, b)
                    # el de respaldo solo donde el lab lo eligió (japonés, coreano)
                    assert name == ROUTES[(a, b)][tier] and supports(name, a, b)
                    assert name != FALLBACK or a in langs.ON_DEMAND


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


def test_manual_translation_is_never_stale(tmp_path):
    """Una frase corregida a mano en el editor de frases no se vuelve a traducir (ni por otro modelo ni por el glosario)."""
    from vt.store import Store

    tr = Store(tmp_path).open("abc12345", "a.mp4")
    tr.set_lang("en")
    a, _ = tr.add_segment(0.0, 1.0, "Hello.", "Hola.", "opus-big")
    b, _ = tr.add_segment(1.0, 2.0, "Quiet.", "Tranquilo.", "opus-big")
    tr.set_translation(b["id"], "Silencioso.", "manual")
    b["manual"] = True
    assert [s["id"] for s in tr.stale("opus-big")] == []
    assert [s["id"] for s in tr.stale("madlad-3b")] == [a["id"]]
