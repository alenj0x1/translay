"""Herramientas de audio propias (solo numpy).

* `resample`         re-muestreo de banda limitada (sinc con ventana Kaiser).
* `time_stretch`     cambia la duración sin cambiar el tono (WSOLA).
* `denoise`          compuerta espectral: limpia las voces de referencia antes
                     de clonarlas (si no, el clon copia el ruido).
* `rms_db`/`match_loudness`  sonoridad.
* `noise`/`mix_at_snr`        ruido de prueba (blanco, rosa, café, zumbido,
                     música, murmullo) mezclado a una relación señal/ruido.
"""

from math import gcd

import numpy as np


# ------------------------------------------------------------------ básicos
def to_mono(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, np.float32)
    return x.mean(axis=1) if x.ndim == 2 else x


def rms_db(x: np.ndarray) -> float:
    if len(x) == 0:
        return -120.0
    return float(10 * np.log10(np.mean(np.square(x, dtype=np.float64)) + 1e-12))


def active_rms_db(x: np.ndarray, sr: int, frame_s: float = 0.03) -> float:
    """Sonoridad de las partes con voz (ignora silencios)."""
    n = int(sr * frame_s)
    k = len(x) // n
    if k == 0:
        return rms_db(x)
    e = np.mean(x[: k * n].reshape(k, n).astype(np.float64) ** 2, axis=1)
    db = 10 * np.log10(e + 1e-12)
    act = db[db > db.max() - 30]
    return float(10 * np.log10(np.mean(10 ** (act / 10)) + 1e-12))


def match_loudness(x: np.ndarray, sr: int, target_db: float, peak: float = 0.97) -> np.ndarray:
    g = 10 ** ((target_db - active_rms_db(x, sr)) / 20)
    y = x * g
    m = np.abs(y).max() if len(y) else 0
    if m > peak:  # limitador simple
        y = y * (peak / m)
    return y.astype(np.float32)


def fade(x: np.ndarray, sr: int, ms: float = 8) -> np.ndarray:
    n = min(len(x) // 2, int(sr * ms / 1000))
    if n > 0:
        r = np.linspace(0, 1, n, dtype=np.float32)
        x = x.copy()
        x[:n] *= r
        x[-n:] *= r[::-1]
    return x


def trim_silence(x: np.ndarray, sr: int, thresh_db: float = 40, pad_s: float = 0.05) -> np.ndarray:
    n = int(sr * 0.02)
    k = len(x) // n
    if k < 3:
        return x
    db = 10 * np.log10(np.mean(x[: k * n].reshape(k, n) ** 2, axis=1) + 1e-12)
    on = np.flatnonzero(db > db.max() - thresh_db)
    if len(on) == 0:
        return x
    a = max(0, on[0] * n - int(pad_s * sr))
    b = min(len(x), (on[-1] + 1) * n + int(pad_s * sr))
    return x[a:b]


# --------------------------------------------------------------- resample
def _kaiser_sinc(up: int, down: int, half_taps: int = 16, beta: float = 8.0) -> np.ndarray:
    cutoff = 0.95 / max(up, down)  # en fracción de la frecuencia de muestreo alta / 2
    n = np.arange(-half_taps * max(up, down), half_taps * max(up, down) + 1)
    h = cutoff * np.sinc(cutoff * n) * np.kaiser(len(n), beta)
    return h


def resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out or len(x) == 0:
        return np.asarray(x, np.float32)
    g = gcd(sr_in, sr_out)
    up, down = sr_out // g, sr_in // g
    h = _kaiser_sinc(up, down)
    h = h / h.sum() * up
    # polifase: y[m] = sum_k x[k] h[m*down - k*up]
    out_len = int(np.ceil(len(x) * up / down))
    xu = np.zeros(len(x) * up, np.float64)
    xu[::up] = x
    y = np.convolve(xu, h, mode="same")[::down]
    return y[:out_len].astype(np.float32)


# ------------------------------------------------------------------ WSOLA
def time_stretch(x: np.ndarray, sr: int, rate: float) -> np.ndarray:
    """rate > 1 acelera (más corto), rate < 1 alarga. El tono se conserva."""
    if abs(rate - 1.0) < 0.01 or len(x) < sr * 0.1:
        return np.asarray(x, np.float32)
    win = int(sr * 0.030)
    win += win % 2
    hop_out = win // 2
    hop_in = hop_out * rate
    tol = int(sr * 0.010)
    w = np.hanning(win).astype(np.float64)
    x = np.concatenate([np.zeros(tol), x.astype(np.float64), np.zeros(win + tol)])
    n_out = int((len(x) - win - 2 * tol) / hop_in)
    y = np.zeros(n_out * hop_out + win)
    norm = np.zeros_like(y)
    prev = None
    for i in range(n_out):
        center = int(round(i * hop_in)) + tol
        if prev is None:
            pos = center
        else:
            # buscar el desplazamiento que mejor continúa el segmento anterior
            seg = x[center - tol: center + tol + hop_out]
            if len(seg) < 2 * tol + hop_out:
                break
            nat = x[prev + hop_out: prev + hop_out + hop_out]
            if len(nat) < hop_out:
                break
            c = np.correlate(seg, nat, mode="valid")
            pos = center - tol + int(np.argmax(c))
        frame = x[pos: pos + win]
        if len(frame) < win:
            break
        o = i * hop_out
        y[o: o + win] += frame * w
        norm[o: o + win] += w
        prev = pos
    norm[norm < 1e-3] = 1.0
    out = (y / norm)[: int(round((len(x) - win - 2 * tol) / rate))]
    return out.astype(np.float32)


# --------------------------------------------------------------- denoise
def _stft(x, n_fft, hop):
    w = np.hanning(n_fft)
    pad = np.concatenate([np.zeros(n_fft // 2), x, np.zeros(n_fft)])
    k = 1 + (len(pad) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(k)[:, None]
    return np.fft.rfft(pad[idx] * w, axis=1), w


def _istft(S, w, n_fft, hop, length):
    frames = np.fft.irfft(S, n=n_fft, axis=1) * w
    y = np.zeros(hop * (len(frames) - 1) + n_fft)
    norm = np.zeros_like(y)
    for i, f in enumerate(frames):
        y[i * hop: i * hop + n_fft] += f
        norm[i * hop: i * hop + n_fft] += w ** 2
    norm[norm < 1e-6] = 1
    y = y / norm
    return y[n_fft // 2: n_fft // 2 + length]


def denoise(x: np.ndarray, sr: int, strength: float = 1.5, floor: float = 0.08) -> np.ndarray:
    """Compuerta espectral con perfil de ruido estimado de las tramas más quietas."""
    if len(x) < sr * 0.3:
        return x
    n_fft = 1024 if sr > 20000 else 512
    hop = n_fft // 4
    S, w = _stft(x.astype(np.float64), n_fft, hop)
    mag = np.abs(S)
    energy = mag.mean(axis=1)
    quiet = mag[energy <= np.percentile(energy, 15)]
    noise = quiet.mean(axis=0) + quiet.std(axis=0)
    gain = np.clip(1 - strength * noise[None, :] / (mag + 1e-9), floor, 1.0)
    # suavizado temporal y frecuencial de la máscara (evita "agua")
    k = np.ones(3) / 3
    gain = np.apply_along_axis(lambda g: np.convolve(g, k, "same"), 0, gain)
    gain = np.apply_along_axis(lambda g: np.convolve(g, k, "same"), 1, gain)
    return _istft(S * gain, w, n_fft, hop, len(x)).astype(np.float32)


def snr_estimate(x: np.ndarray, sr: int) -> float:
    """SNR aproximada: energía de tramas fuertes vs. tramas quietas (dB)."""
    n = int(sr * 0.03)
    k = len(x) // n
    if k < 5:
        return 0.0
    e = np.sort(np.mean(x[: k * n].reshape(k, n).astype(np.float64) ** 2, axis=1))
    lo = e[: max(1, k // 10)].mean()
    hi = e[-max(1, k // 3):].mean()
    return float(10 * np.log10((hi + 1e-12) / (lo + 1e-12)))


# ---------------------------------------------------------- ruido de prueba
def noise(kind: str, n: int, sr: int, seed: int = 0, speech_pool: list | None = None) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(n) / sr
    if kind == "white":
        y = rng.standard_normal(n)
    elif kind in ("pink", "brown"):
        f = np.fft.rfftfreq(n, 1 / sr)
        spec = np.fft.rfft(rng.standard_normal(n))
        spec[1:] /= f[1:] ** (0.5 if kind == "pink" else 1.0)
        spec[0] = 0
        y = np.fft.irfft(spec, n)
    elif kind == "hum":
        y = sum(np.sin(2 * np.pi * 60 * h * t) / h for h in range(1, 8))
        y = y + 0.3 * noise("pink", n, sr, seed)
    elif kind == "music":
        # acordes con envolventes + bajo, ritmo de 100 bpm
        y = np.zeros(n)
        beat = int(sr * 0.6)
        chords = [[220, 277, 330], [196, 247, 294], [175, 220, 262], [196, 247, 294]]
        for i, start in enumerate(range(0, n, beat * 4)):
            ch = chords[i % 4]
            seg = slice(start, min(n, start + beat * 4))
            tt = t[seg] - t[start]
            env = np.exp(-tt * 0.8)
            for fr in ch:
                y[seg] += env * np.sin(2 * np.pi * fr * tt) * 0.3
            y[seg] += np.sin(2 * np.pi * ch[0] / 2 * tt) * 0.4
        for start in range(0, n, beat):  # percusión
            m = min(n - start, int(sr * 0.05))
            y[start:start + m] += rng.standard_normal(m) * np.exp(-np.arange(m) / (sr * 0.01))
    elif kind == "babble":
        # murmullo: varias voces superpuestas, invertidas (sin palabras legibles)
        y = np.zeros(n)
        pool = speech_pool or [rng.standard_normal(sr * 3)]
        for j in range(6):
            src = pool[j % len(pool)][::-1]
            off = rng.integers(0, max(1, len(src)))
            rep = np.resize(np.roll(src, off), n)
            y += rep * rng.uniform(0.5, 1.0)
    elif kind == "cafe":
        y = noise("babble", n, sr, seed, speech_pool) + 0.5 * noise("pink", n, sr, seed + 1)
        for _ in range(max(1, n // (sr * 2))):  # golpes de vajilla
            p = rng.integers(0, n)
            m = min(n - p, int(sr * 0.08))
            y[p:p + m] += 3 * rng.standard_normal(m) * np.exp(-np.arange(m) / (sr * 0.008))
    else:
        raise ValueError(kind)
    y = np.asarray(y, np.float64)
    return (y / (np.sqrt(np.mean(y ** 2)) + 1e-12)).astype(np.float32)


def mix_at_snr(clean: np.ndarray, nz: np.ndarray, snr_db: float, sr: int) -> np.ndarray:
    nz = np.resize(nz, len(clean))
    p_s = 10 ** (active_rms_db(clean, sr) / 10)
    p_n = np.mean(nz.astype(np.float64) ** 2)
    y = clean + nz * np.sqrt(p_s / (p_n * 10 ** (snr_db / 10)))
    m = np.abs(y).max()
    return (y / m * 0.95 if m > 0.95 else y).astype(np.float32)


# ------------------------------------------------------------------ WAV io
def read_wav(path) -> tuple[np.ndarray, int]:
    import wave

    with wave.open(str(path), "rb") as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if sw == 2:
        x = np.frombuffer(raw, "<i2").astype(np.float32) / 32768
    elif sw == 4:
        x = np.frombuffer(raw, "<i4").astype(np.float32) / 2 ** 31
    else:
        raise ValueError(f"WAV de {sw * 8} bits no soportado")
    return (x.reshape(-1, ch).mean(axis=1) if ch > 1 else x), sr


def write_wav(path, x: np.ndarray, sr: int):
    import wave

    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


# ------------------------------------------------------------------- tono
def f0_track(x: np.ndarray, sr: int, fmin: float = 60, fmax: float = 400,
             frame_s: float = 0.04, hop_s: float = 0.01, thresh: float = 0.15) -> np.ndarray:
    """F0 por trama con YIN (0 = sin voz)."""
    n, hop = int(sr * frame_s), int(sr * hop_s)
    tmin, tmax = int(sr / fmax), int(sr / fmin)
    out = []
    for i in range(0, len(x) - n - tmax, hop):
        fr = x[i:i + n + tmax].astype(np.float64)
        if np.mean(fr[:n] ** 2) < 1e-5:
            out.append(0.0)
            continue
        # diferencia acumulada normalizada (YIN), vía FFT
        d = np.array([np.sum((fr[:n] - fr[t:t + n]) ** 2) for t in range(tmax + 1)])
        cmnd = d.copy()
        cmnd[1:] = d[1:] * np.arange(1, tmax + 1) / (np.cumsum(d[1:]) + 1e-12)
        cmnd[0] = 1
        cand = np.flatnonzero(cmnd[tmin:] < thresh)
        if len(cand) == 0:
            out.append(0.0)
            continue
        t = cand[0] + tmin
        while t + 1 <= tmax and cmnd[t + 1] < cmnd[t]:
            t += 1
        out.append(sr / t)
    return np.array(out)


def median_f0(x: np.ndarray, sr: int) -> float:
    f = f0_track(x, sr)
    f = f[f > 0]
    return float(np.median(f)) if len(f) > 5 else 0.0


def enhance(x: np.ndarray, sr: int, alpha: float = 0.98, floor_db: float = -18.0,
            win_s: float = 1.2, over: float = 1.3) -> np.ndarray:
    """Realce de voz: Wiener con SNR a priori "dirigida por decisión"
    (Ephraim-Malah) y ruido estimado por mínimos estadísticos, que sigue al
    ruido aunque cambie y no necesita tramos de silencio."""
    if len(x) < sr * 0.3:
        return x
    n_fft = 512 if sr <= 16000 else 1024
    hop = n_fft // 4
    S, w = _stft(x.astype(np.float64), n_fft, hop)
    P = np.abs(S) ** 2
    T = len(P)
    # PSD suavizada y su mínimo en una ventana deslizante (sesgo compensado)
    sm = np.empty_like(P)
    acc = P[0]
    for t in range(T):
        acc = 0.8 * acc + 0.2 * P[t]
        sm[t] = acc
    L = max(4, int(win_s * sr / hop))
    noise = np.empty_like(P)
    for t in range(T):
        noise[t] = sm[max(0, t - L): t + 1].min(axis=0) * 1.5 * over
    noise = np.maximum(noise, 1e-12)
    G = np.empty_like(P)
    g_prev = np.ones(P.shape[1])
    gamma_prev = np.ones(P.shape[1])
    gmin = 10 ** (floor_db / 20)
    for t in range(T):
        gamma = P[t] / noise[t]
        xi = alpha * g_prev ** 2 * gamma_prev + (1 - alpha) * np.maximum(gamma - 1, 0)
        xi = np.maximum(xi, 10 ** (-25 / 10))
        g = np.maximum(xi / (1 + xi), gmin)
        G[t] = g
        g_prev, gamma_prev = g, gamma
    return _istft(S * G, w, n_fft, hop, len(x)).astype(np.float32)
