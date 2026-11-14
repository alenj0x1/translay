"""Laboratorio del agente (vt/agent.py + vt/llm.py): qué modelo y qué motor para cada equipo.

  python tools/lab/agent.py --profile gpu-vulkan                       todos los modelos, todas las preguntas
  python tools/lab/agent.py --profile cpu-4t --models qwen3-1.7b lfm2.5-1.2b
  python tools/lab/agent.py --report                                   tabla con lo medido

Perfiles (simulan equipos en este, con los mismos binarios que la app):
  cpu-4t      solo CPU, 4 hilos: una laptop modesta; el video por fragmentos (2.500 tokens)
  cpu-6t      solo CPU, 6 hilos: un escritorio sin GPU; fragmentos (5.000 tokens)
  igpu        gráfica integrada (Intel UHD 730) por Vulkan; el video entero hasta 10.000 tokens
  gpu-vulkan  NVIDIA por Vulkan (el build liviano, 38 MB); entero hasta 24.000 tokens
  gpu-cuda    NVIDIA por CUDA (700 MB): ¿vale la pena frente a Vulkan?

Preguntas: tools/lab/agent_questions.json (con el momento que debe citar y palabras clave; las «trampa»
preguntan algo que el video no dice). Material: data/labs/agent/videos/ (tools/lab/agent_fixtures.py).

Por respuesta: tiempo hasta la primera palabra (ttft), tokens del prompt y cuántos venían de la caché,
velocidad de generación, RAM máxima del servidor, y calidad: claves (0–1), cita del momento correcto,
español, honestidad en las trampas. Resultados en data/labs/agent/out/<perfil>.jsonl.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from vt import agent, llm  # noqa: E402
from vt.store import Transcript  # noqa: E402

LAB = ROOT / "data" / "labs" / "agent"
VIDEOS = LAB / "videos"
OUT = LAB / "out"
QUESTIONS = Path(__file__).with_name("agent_questions.json")
PROFILES = {
    "cpu-4t": dict(build="cpu", threads=4, ngl=0, budget=2500, ctx=4096),
    "cpu-6t": dict(build="cpu", threads=6, ngl=0, budget=5000, ctx=8192),
    "igpu": dict(build="vulkan", device="Vulkan1", ngl=99, budget=10000, ctx=12288),
    "gpu-vulkan": dict(build="vulkan", device="Vulkan0", ngl=99, budget=24000, ctx=32768),
    "gpu-cuda": dict(build="cuda", ngl=99, budget=24000, ctx=32768),
}
_ES = set("el la los las de que y en un una por para con no es se lo del al como más pero sus le ya o este sí "
          "porque esta entre cuando muy sin sobre también me hasta hay donde quien desde todo nos durante todos "
          "uno les ni contra otros ese eso ante ellos e esto mí antes algunos qué unos yo otro otras otra él tanto "
          "esa estos mucho quienes nada muchos cual poco ella estar estas algunas algo nosotros video usa dice".split())
_EN = set("the of and to in is you that it he was for on are as with his they i at be this have from or one had "
          "by word but not what all were we when your can said there use an each which she do how their if will "
          "up other about out many then them these so".split())


def load_video(name: str):
    data = json.loads((VIDEOS / f"{name}.json").read_text(encoding="utf-8"))
    tr = Transcript(VIDEOS / f"{name}.json", data)
    sp = VIDEOS / f"{name}.screen.json"
    screen = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else None
    segs = data["segments"]
    info = {"title": data.get("name", name), "duration": segs[-1]["end"] if segs else 0,
            "url": f"https://www.youtube.com/watch?v={data['youtube']}" if data.get("youtube") else ""}
    return info, tr, screen


def spanish(text: str) -> bool:
    w = re.findall(r"[a-záéíóúñ]+", text.lower())
    return sum(x in _ES for x in w) > sum(x in _EN for x in w)


def grade(q: dict, text: str) -> dict:
    low = text.lower()
    groups = q.get("keys", [])

    def hit(k: str) -> bool:  # las claves cortas («no», «py», «p») como palabra entera
        k = k.lower().strip()
        return bool(re.search(rf"(?<![\w]){re.escape(k)}(?![\w])", low)) if len(k) <= 3 else k in low
    keys = sum(any(hit(k) for k in g) for g in groups) / len(groups) if groups else 1.0
    cited = agent.stamps(text)
    ok_stamp = None
    if q.get("at"):
        ok_stamp = any(a - 8 <= t <= b + 8 for t in cited for a, b in q["at"])
    es = spanish(text)
    if q.get("trap"):
        score = 0.7 * keys + 0.3 * es
    else:
        score = 0.5 * keys + 0.3 * bool(ok_stamp) + 0.2 * es
    return {"keys": round(keys, 2), "stamp_ok": ok_stamp, "cited": cited[:6], "spanish": es, "score": round(score, 3)}


_THINK = re.compile(r"<think>.*?</think>\s*", re.S)


def gpu_busy() -> int:
    """% de uso de la NVIDIA ahora (otra carga en la GPU arruina la medición: la primera tanda midió
    200 tokens/s en vez de 5.200 porque Whisper transcribía al mismo tiempo)."""
    import subprocess

    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
        return max(int(x) for x in out.split())
    except Exception:  # noqa: BLE001
        return 0


def vram_used() -> int:
    import subprocess

    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
        return int(out.split()[0])
    except Exception:  # noqa: BLE001
        return 0


def run(profile: str, models: list[str], only_videos: list[str] | None = None, max_tokens: int = 350):
    p = PROFILES[profile]
    if p["ngl"] and p.get("device") != "Vulkan1":
        for _ in range(12):  # hasta un minuto esperando que la GPU se libere
            if gpu_busy() < 20:
                break
            time.sleep(5)
        else:
            raise SystemExit("la GPU está ocupada por otro programa: la medición no sería válida")
    exe = llm.ensure(p["build"], LAB)
    qs = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    vids = sorted({q["video"] for q in qs if (VIDEOS / f"{q['video']}.json").exists()})
    if only_videos:
        vids = [v for v in vids if v in only_videos]
    OUT.mkdir(parents=True, exist_ok=True)
    out = (OUT / f"{profile}.jsonl").open("a", encoding="utf-8")
    for key in models:
        m = llm.MODELS[key]
        try:
            path = llm.model_file(key)
        except Exception as e:  # noqa: BLE001
            print(f"{key}: no se pudo bajar ({e})", flush=True)
            continue
        srv = llm.Server(exe, path, ctx=p["ctx"], threads=p.get("threads", 0), gpu_layers=p["ngl"],
                         device=p.get("device"), log=OUT / f"{profile}-{key}.log")
        vram0 = vram_used()
        try:
            srv.start()
        except Exception as e:  # noqa: BLE001
            print(f"{key}: no cargó ({e})", flush=True)
            out.write(json.dumps({"profile": profile, "model": key, "error": str(e)}) + "\n")
            continue
        # calentamiento: Vulkan compila sus shaders la primera vez (no es parte de lo que se mide)
        warm = time.perf_counter()
        try:
            srv.chat([{"role": "user", "content": "Hola"}], max_tokens=4, chat_template_kwargs={"enable_thinking": False})
        except Exception:  # noqa: BLE001
            pass
        vram = max(0, vram_used() - vram0) if p["ngl"] and p.get("device") != "Vulkan1" else 0
        print(f"== {profile} · {m.name}: cargó en {srv.load_s:.1f} s, calentó en {time.perf_counter() - warm:.1f} s"
              + (f", VRAM {vram} MB" if vram else ""), flush=True)
        try:
            for v in vids:
                info, tr, screen = load_video(v)
                for q in [q for q in qs if q["video"] == v]:
                    msgs, mode = agent.messages(info, tr, screen, q["q"], position=q.get("position"),
                                                budget=p["budget"])
                    t0 = time.perf_counter()
                    try:
                        r = srv.chat(msgs, max_tokens=max_tokens, temperature=0.2,
                                     chat_template_kwargs={"enable_thinking": False})
                    except Exception as e:  # noqa: BLE001
                        r = {"text": "", "error": str(e)[:200], "total_s": time.perf_counter() - t0}
                    text = _THINK.sub("", r.get("text", "")).strip()
                    g = grade(q, text)
                    row = {"profile": profile, "model": key, "video": v, "q": q["q"], "mode": mode, **r, **g,
                           "text": text, **srv.memory(), "load_s": round(srv.load_s, 1), "vram_mb": vram, "time": time.time()}
                    out.write(json.dumps(row, ensure_ascii=False) + "\n")
                    out.flush()
                    print(f"  {v:14} {g['score']:.2f} ttft {r.get('ttft_s', 0):5.1f}s gen {r.get('gen_tps') or 0:5.1f} t/s "
                          f"prompt {r.get('prompt_n')}/{(r.get('prompt_n') or 0) + (r.get('cached_n') or 0)} "
                          f"{mode[:4]} · {q['q'][:40]}", flush=True)
        finally:
            srv.stop()


def report():
    import statistics as st

    regrade()  # con las citas propias de la app (vt/agent.cite), que es lo que ve la persona
    rows = []
    for f in sorted(OUT.glob("*.jsonl")):
        rows += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    rows = [r for r in rows if "score" in r]
    by: dict = {}
    for r in rows:
        by.setdefault((r["profile"], r["model"]), []).append(r)
    print(f"{'perfil':11} {'modelo':16} {'n':>3} {'calidad':>7} {'cita':>5} {'trampas':>7} {'ttft p50':>8} {'ttft p95':>8} "
          f"{'gen t/s':>7} {'RAM pico':>8}")
    for (p, m), rs in sorted(by.items(), key=lambda kv: (kv[0][0], -st.mean(r["score"] for r in kv[1]))):
        tt = sorted(r["ttft_s"] or r["total_s"] for r in rs)
        traps = [r for r in rs if r["stamp_ok"] is None and r["keys"] is not None]
        cites = [r["stamp_ok"] for r in rs if r["stamp_ok"] is not None]
        cites = [bool(r.get("cited_stamp_ok")) for r in rs if r["stamp_ok"] is not None]
        print(f"{p:11} {m:16} {len(rs):3} {st.mean(r.get('cited_score', r['score']) for r in rs):7.2f} "
              f"{(sum(cites) / len(cites) if cites else 0):5.0%} {st.mean(r['keys'] for r in traps) if traps else 0:7.2f} "
              f"{tt[len(tt) // 2]:7.1f}s {tt[min(len(tt) - 1, int(len(tt) * .95))]:7.1f}s "
              f"{st.mean([r['gen_tps'] or 0 for r in rs]):7.1f} {max(r.get('peak_mb', 0) for r in rs):7d}M")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", choices=list(PROFILES))
    ap.add_argument("--models", nargs="*", default=None)
    ap.add_argument("--videos", nargs="*", default=None)
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if a.report:
        return report()
    run(a.profile, a.models or list(llm.MODELS), a.videos)



def regrade(files: list[Path] | None = None):
    """Vuelve a calificar las respuestas guardadas: tal cual y con las citas propias (vt/agent.cite)."""
    qs = {(q["video"], q["q"]): q for q in json.loads(QUESTIONS.read_text(encoding="utf-8"))}
    vids: dict = {}
    for f in files or sorted(OUT.glob("*.jsonl")):
        rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
        for r in rows:
            if "text" not in r or (r["video"], r["q"]) not in qs:
                continue
            q = qs[(r["video"], r["q"])]
            if r["video"] not in vids:
                vids[r["video"]] = load_video(r["video"])
            _, tr, screen = vids[r["video"]]
            r.update(grade(q, r["text"]))
            cited = agent.cite(r["text"], tr, screen)
            g = grade(q, cited)
            r.update(cited_score=g["score"], cited_stamp_ok=g["stamp_ok"])
        f.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


if __name__ == "__main__":
    main()
