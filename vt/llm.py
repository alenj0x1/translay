"""Modelos de lenguaje locales con llama.cpp (`llama-server`), para el agente de cada video (vt/agent.py).

Un solo motor para todos los equipos: llama.cpp (MIT) con
  cpu      CPU (AVX2), cualquier equipo
  vulkan   GPU por Vulkan: integradas Intel y AMD, y también NVIDIA (sin instalar CUDA)
  cuda     NVIDIA con CUDA 12.4 (más grande: el laboratorio dice si vale la pena frente a Vulkan)
Cada build se baja de las releases oficiales con la versión fija, se verifica su SHA-256 y se descomprime
en <datos>/runtime/llama/<versión>/<build>/. No pide permisos de administrador.

Los modelos (GGUF) salen de Hugging Face con la revisión fija (MODELS). El servidor escucha solo en
127.0.0.1, en un puerto libre, y se cierra con la app (o al quedar sin uso).

  ensure(build, root)            el llama-server.exe de ese build (lo baja si falta)
  model_file(key)                el GGUF del modelo (lo baja si falta)
  Server(...).start() / chat()   levantar el modelo y conversar (con streaming y tiempos)
  devices(exe)                   las GPU que ve un build (para elegir integrada o dedicada)
"""

from __future__ import annotations

import ctypes
import hashlib
import http.client
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

RELEASE = "b12383"
_BASE = f"https://github.com/ggml-org/llama.cpp/releases/download/{RELEASE}/"
# build → [(archivo, bytes, sha256)]; cuda lleva además sus bibliotecas (cudart)
BUILDS = {
    "cpu": [(f"llama-{RELEASE}-bin-win-cpu-x64.zip", 25_124_601,
             "ad5bf0d826ea1f39aaf9721b7e26fde9be0bef5d9b69b9ba88c2d083b9a3bca7")],
    "vulkan": [(f"llama-{RELEASE}-bin-win-vulkan-x64.zip", 38_118_260,
                "bb6c4a8e51618269a063a87a1ecdee465d76fea483b7ee1824bb1f92ce997c0b")],
    "cuda": [(f"llama-{RELEASE}-bin-win-cuda-12.4-x64.zip", 319_406_002,
              "9d20d213df59098778131f5fb792e37300e954f6d6c283aed59e68c26d4fa07b"),
             ("cudart-llama-bin-win-cuda-12.4-x64.zip", 391_443_627,
              "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6")],
}


@dataclass(frozen=True)
class Model:
    key: str
    name: str
    repo: str
    rev: str
    file: str
    gb: float          # lo que pesa el archivo
    license: str
    note: str = ""


# candidatos (el laboratorio tools/lab/agent.py decide cuáles quedan y para qué equipo)
MODELS = {m.key: m for m in [
    Model("lfm2.5-350m", "LFM2.5 350M", "LiquidAI/LFM2.5-350M-GGUF", "657e078c94", "LFM2.5-350M-Q4_K_M.gguf", 0.23, "LFM Open 1.0"),
    Model("qwen3-0.6b", "Qwen3 0.6B", "Qwen/Qwen3-0.6B-GGUF", "23749fefcc", "Qwen3-0.6B-Q8_0.gguf", 0.64, "Apache-2.0"),
    Model("qwen3.5-0.8b", "Qwen3.5 0.8B", "ggml-org/Qwen3.5-0.8B-GGUF", "004fd086ec", "Qwen3.5-0.8B-Q8_0.gguf", 0.83, "Apache-2.0"),
    Model("gemma3-1b", "Gemma 3 1B", "ggml-org/gemma-3-1b-it-GGUF", "f9c28bcd85", "gemma-3-1b-it-Q4_K_M.gguf", 0.81, "Gemma"),
    Model("lfm2.5-1.2b", "LFM2.5 1.2B", "LiquidAI/LFM2.5-1.2B-Instruct-GGUF", "8ed288026e", "LFM2.5-1.2B-Instruct-Q4_K_M.gguf", 0.73, "LFM Open 1.0"),
    Model("granite4-1b", "Granite 4.0 H 1B", "ibm-granite/granite-4.0-h-1b-GGUF", "c2cb1972f5", "granite-4.0-h-1b-Q4_K_M.gguf", 0.90, "Apache-2.0"),
    Model("llama3.2-1b", "Llama 3.2 1B", "bartowski/Llama-3.2-1B-Instruct-GGUF", "067b946cf0", "Llama-3.2-1B-Instruct-Q4_K_M.gguf", 0.81, "Llama 3.2"),
    Model("qwen3-1.7b", "Qwen3 1.7B", "ggml-org/Qwen3-1.7B-GGUF", "daeb8e2d52", "Qwen3-1.7B-Q4_K_M.gguf", 1.28, "Apache-2.0"),
    Model("qwen3.5-2b", "Qwen3.5 2B", "unsloth/Qwen3.5-2B-GGUF", "f6d5376be1", "Qwen3.5-2B-Q4_K_M.gguf", 1.28, "Apache-2.0"),
    Model("smollm3-3b", "SmolLM3 3B", "ggml-org/SmolLM3-3B-GGUF", "4965cb60b1", "SmolLM3-Q4_K_M.gguf", 1.92, "Apache-2.0"),
    Model("granite4-micro", "Granite 4.0 H Micro (3B)", "ibm-granite/granite-4.0-h-micro-GGUF", "dc1dd2585f", "granite-4.0-h-micro-Q4_K_M.gguf", 1.94, "Apache-2.0"),
    Model("llama3.2-3b", "Llama 3.2 3B", "bartowski/Llama-3.2-3B-Instruct-GGUF", "5ab33fa94d", "Llama-3.2-3B-Instruct-Q4_K_M.gguf", 2.02, "Llama 3.2"),
    Model("gemma4-e2b", "Gemma 4 E2B", "unsloth/gemma-4-E2B-it-GGUF", "0314792d7f", "gemma-4-E2B-it-Q4_K_M.gguf", 3.11, "Apache-2.0"),
    Model("qwen3-4b", "Qwen3 4B Instruct 2507", "unsloth/Qwen3-4B-Instruct-2507-GGUF", "a06e946bb6", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf", 2.50, "Apache-2.0"),
    Model("qwen3.5-4b", "Qwen3.5 4B", "unsloth/Qwen3.5-4B-GGUF", "e87f176479", "Qwen3.5-4B-Q4_K_M.gguf", 2.74, "Apache-2.0"),
    Model("phi4-mini", "Phi-4 mini", "unsloth/Phi-4-mini-instruct-GGUF", "78eb92a46f", "Phi-4-mini-instruct-Q4_K_M.gguf", 2.49, "MIT"),
    Model("gemma4-e4b", "Gemma 4 E4B", "unsloth/gemma-4-E4B-it-GGUF", "bfc15c3822", "gemma-4-E4B-it-Q4_K_M.gguf", 4.98, "Apache-2.0"),
    Model("qwen3.5-9b", "Qwen3.5 9B", "unsloth/Qwen3.5-9B-GGUF", "3885219b68", "Qwen3.5-9B-Q4_K_M.gguf", 5.68, "Apache-2.0"),
]}


# ------------------------------------------------------------------ binarios
def build_dir(root: Path, build: str) -> Path:
    return Path(root) / "runtime" / "llama" / RELEASE / build


def _download(url: str, dest: Path, size: int, sha: str, progress=None):
    h = hashlib.sha256()
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "Translay"})
    done = 0
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, size)
    if h.hexdigest() != sha:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"{dest.name}: la descarga no coincide con la verificada (SHA-256)")
    tmp.replace(dest)


def ensure(build: str, root: Path, progress=None) -> Path:
    """El llama-server.exe de ese build, listo para usar (se baja y verifica la primera vez)."""
    d = build_dir(root, build)
    exe = d / "llama-server.exe"
    if exe.exists():
        return exe
    work = d.with_name(d.name + ".tmp")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        for name, size, sha in BUILDS[build]:
            z = work / name
            _download(_BASE + name, z, size, sha, progress)
            with zipfile.ZipFile(z) as zf:
                for m in zf.namelist():  # nada fuera de la carpeta
                    if m.startswith(("/", "\\")) or ".." in Path(m).parts:
                        raise RuntimeError(f"{name}: ruta inválida en el zip")
                zf.extractall(work)
            z.unlink()
        # algunos zips traen una carpeta adentro: los binarios quedan arriba
        inner = next(work.rglob("llama-server.exe"), None)
        if inner is None:
            raise RuntimeError("el zip no trae llama-server.exe")
        if inner.parent != work:
            for p in inner.parent.iterdir():
                shutil.move(str(p), work / p.name)
        shutil.rmtree(d, ignore_errors=True)
        work.replace(d)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    return exe


def devices(exe: Path) -> list[dict]:
    """Las GPU que ve un build: [{id, name, mb}] (`llama-server --list-devices`)."""
    try:
        out = subprocess.run([str(exe), "--list-devices"], capture_output=True, text=True, timeout=60,
                             creationflags=_NO_WINDOW).stdout + ""
    except (OSError, subprocess.TimeoutExpired):
        return []
    import re

    found = []
    # «Vulkan0: NVIDIA GeForce RTX 4060 (7956 MiB, 7188 MiB free)»; la integrada informa la memoria compartida
    for m in re.finditer(r"^\s*(\w+\d+):\s*(.+?)\s*\((\d+) MiB,\s*(\d+) MiB free\)", out, re.M):
        name = m.group(2)
        found.append({"id": m.group(1), "name": name, "mb": int(m.group(3)), "free_mb": int(m.group(4)),
                      "integrated": bool(re.search(r"Intel\(R\) (?:UHD|Iris|HD)|Radeon\(TM\) (?:Graphics|Vega)|"
                                                   r"AMD Radeon(?:\(TM\))? (?:\d{3}M|Graphics)|Arc\(TM\) Graphics", name))})
    return found


# ------------------------------------------------------------------ modelos
def model_file(key: str, download: bool = True, tqdm_class=None) -> Path | None:
    from huggingface_hub import hf_hub_download

    m = MODELS[key]
    try:
        return Path(hf_hub_download(m.repo, m.file, revision=m.rev, local_files_only=not download,
                                    tqdm_class=tqdm_class))
    except Exception:
        if download:
            raise
        return None


# ------------------------------------------------------------------ servidor
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _PMC(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def proc_memory(p: subprocess.Popen) -> dict:
    """Memoria del proceso por su propio handle: {ram_mb, peak_mb, commit_mb} (Windows)."""
    if sys.platform != "win32":
        return {}
    c = _PMC()
    c.cb = ctypes.sizeof(c)
    if not ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(int(p._handle)), ctypes.byref(c), c.cb):
        return {}
    mb = 1 << 20
    return {"ram_mb": c.WorkingSetSize // mb, "peak_mb": c.PeakWorkingSetSize // mb, "commit_mb": c.PeakPagefileUsage // mb}


def _bind(proc: subprocess.Popen):
    """Ata el llama-server a este proceso: si Translay se cierra de golpe (sin atexit), Windows lo cierra
    también y el modelo no queda ocupando memoria (un Job Object propio con KILL_ON_JOB_CLOSE)."""
    if sys.platform != "win32":
        return None
    try:
        from .limits import Job
        job = Job(kill_on_close=True)
        job.add(proc)
        return job
    except Exception:  # sin job el servidor igual funciona; stop() y atexit lo cierran
        return None


class Server:
    """Un llama-server con un modelo. gpu_layers 0 = solo CPU; device elige la GPU de Vulkan/CUDA."""

    def __init__(self, exe: Path, model: Path, ctx: int = 8192, threads: int = 0, gpu_layers: int = 0,
                 device: str | None = None, kv: str = "q8_0", fa: str = "on", extra: list[str] | None = None, log: Path | None = None,
                 low_priority: bool = False):
        self.exe, self.model, self.ctx, self.threads = Path(exe), Path(model), ctx, threads
        self.gpu_layers, self.device, self.kv, self.extra, self.log = gpu_layers, device, kv, extra or [], log
        self.fa = fa
        self.low_priority = low_priority  # en la CPU: cede los núcleos a lo que la persona está usando
        self.port = 0
        self.proc: subprocess.Popen | None = None
        self.load_s = 0.0

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self, timeout: float = 300):
        self.port = _free_port()
        cmd = [str(self.exe), "-m", str(self.model), "--host", "127.0.0.1", "--port", str(self.port),
               "-c", str(self.ctx), "-ngl", str(self.gpu_layers), "--jinja", "-np", "1",
               "--cache-type-k", self.kv, "--cache-type-v", self.kv, "-fa", self.fa, "--no-webui"]
        if self.threads:
            cmd += ["-t", str(self.threads), "-tb", str(self.threads)]
        if self.device:
            cmd += ["--device", self.device]
        cmd += self.extra
        out = open(self.log, "ab") if self.log else subprocess.DEVNULL
        t0 = time.perf_counter()
        self.proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, creationflags=_NO_WINDOW,
                                     cwd=str(self.exe.parent))
        self._job = _bind(self.proc)
        if self.low_priority and sys.platform == "win32":
            ctypes.windll.kernel32.SetPriorityClass(int(self.proc._handle), 0x4000)  # BELOW_NORMAL_PRIORITY_CLASS
        while time.perf_counter() - t0 < timeout:
            if self.proc.poll() is not None:
                raise RuntimeError(f"llama-server terminó al cargar (código {self.proc.returncode})")
            try:
                with urllib.request.urlopen(self.url + "/health", timeout=2) as r:
                    if json.loads(r.read()).get("status") == "ok":
                        self.load_s = time.perf_counter() - t0
                        return self
            except Exception:
                pass
            time.sleep(0.25)
        self.stop()
        raise TimeoutError("el modelo no terminó de cargar")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def memory(self) -> dict:
        return proc_memory(self.proc) if self.proc else {}

    def chat(self, messages: list[dict], max_tokens: int = 512, temperature: float = 0.3, on_text=None,
             stop_flag=None, **params) -> dict:
        """Conversa (streaming). on_text(trozo) recibe el texto a medida que sale. Devuelve
        {text, ttft_s, total_s, prompt_n, prompt_ms, gen_n, gen_tps, cached_n}."""
        body = {"messages": messages, "max_tokens": max_tokens, "temperature": temperature, "stream": True,
                "cache_prompt": True, "timings_per_token": False, **params}
        t0 = time.perf_counter()
        ttft = None
        text, timings = [], {}
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=1800)
        # detener: mientras lee el video (lo más largo) no sale ningún trozo, y en Windows cerrar la conexión no
        # despierta una lectura en curso; por eso lee un hilo aparte y aquí se espera con pausas cortas: al
        # detener se suelta al instante, se cierra la conexión y llama-server, al verla cerrada, deja la tarea
        lines: queue.Queue = queue.Queue()
        stopped = False

        def read():
            try:
                conn.request("POST", "/v1/chat/completions", body=json.dumps(body).encode(),
                             headers={"Content-Type": "application/json"})
                r = conn.getresponse()
                if r.status != 200:
                    raise RuntimeError(f"llama-server respondió {r.status}: {r.read(300).decode('utf-8', 'replace')}")
                for raw in r:
                    lines.put(raw)
                lines.put(None)
            except BaseException as e:  # noqa: BLE001
                lines.put(e)
        threading.Thread(target=read, daemon=True, name="llm-leer").start()
        try:
            while True:
                try:
                    raw = lines.get(timeout=0.1)
                except queue.Empty:
                    if stop_flag and stop_flag():
                        stopped = True
                        break
                    continue
                if raw is None:
                    break
                if isinstance(raw, BaseException):
                    raise raw
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                d = json.loads(data)
                if d.get("timings"):
                    timings = d["timings"]
                for ch in d.get("choices", []):
                    piece = (ch.get("delta") or {}).get("content") or ""
                    if piece:
                        if ttft is None:
                            ttft = time.perf_counter() - t0
                        text.append(piece)
                        if on_text:
                            on_text(piece)
                if stop_flag and stop_flag():
                    stopped = True
                    break
        finally:
            try:
                if conn.sock:
                    conn.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            conn.close()
        return {"text": "".join(text), "stopped": stopped,
                "ttft_s": round(ttft or 0, 3), "total_s": round(time.perf_counter() - t0, 3),
                "prompt_n": timings.get("prompt_n"), "prompt_ms": timings.get("prompt_ms"),
                "cached_n": timings.get("cache_n"), "gen_n": timings.get("predicted_n"),
                "gen_tps": timings.get("predicted_per_second"), "pp_tps": timings.get("prompt_per_second")}

    def tokens(self, text: str) -> int:
        req = urllib.request.Request(self.url + "/tokenize", data=json.dumps({"content": text}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return len(json.loads(r.read())["tokens"])


def _cli():
    """python -m vt.llm devices|get <build> --root D  (pruebas a mano)"""
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["get", "devices"])
    ap.add_argument("build", choices=list(BUILDS))
    ap.add_argument("--root", default="data")
    a = ap.parse_args()
    exe = ensure(a.build, Path(a.root), lambda d, t: print(f"\r{d * 100 // max(1, t)}%", end="", flush=True))
    print("\n", exe)
    if a.what == "devices":
        print(json.dumps(devices(exe), indent=1))


if __name__ == "__main__":
    _cli()
