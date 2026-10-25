"""Realce neuronal de voz (DeepFilterNet3) para limpiar voces de referencia.

Corre dentro del proceso de voz (entorno con torch). DeepFilterNet importa un
módulo que torchaudio ≥2.9 eliminó; se sustituye por uno mínimo antes de importar.
"""

import sys
import types

import numpy as np


def _shim_torchaudio():
    if "torchaudio.backend.common" in sys.modules:
        return
    import torchaudio  # noqa: F401

    backend = types.ModuleType("torchaudio.backend")
    common = types.ModuleType("torchaudio.backend.common")

    class AudioMetaData:  # solo se usa como anotación de tipos
        pass

    common.AudioMetaData = AudioMetaData
    backend.common = common
    sys.modules["torchaudio.backend"] = backend
    sys.modules["torchaudio.backend.common"] = common


class Enhancer:
    def __init__(self):
        _shim_torchaudio()
        from df.enhance import init_df

        self.model, self.state, _ = init_df(log_level="ERROR")
        self.sr = self.state.sr()

    def __call__(self, x: np.ndarray, sr: int, atten_db: float = 30.0) -> np.ndarray:
        import torch
        from df.enhance import enhance

        sys.path.insert(0, __file__.rsplit("vt", 1)[0])
        from vt.audiofx import resample

        y = resample(x, sr, self.sr)
        out = enhance(self.model, self.state, torch.from_numpy(y)[None], atten_lim_db=atten_db)
        return resample(out[0].numpy().astype(np.float32), self.sr, sr)
