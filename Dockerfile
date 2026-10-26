# syntax=docker/dockerfile:1.7
# Translay: servidor (Python 3.12 + CTranslate2) y motor de voz OmniVoice (Python 3.11 + torch)
# en una imagen con CUDA 12.8 y cuDNN 9. Necesita una GPU NVIDIA y NVIDIA Container Toolkit.
#
#   docker compose up -d            (ver docker-compose.yml)
#   docker build -t translay .      (solo la imagen)

ARG CUDA_IMAGE=nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04

FROM ghcr.io/astral-sh/uv:0.13.0 AS uv
FROM node:22-bookworm-slim AS node

FROM ${CUDA_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_COMPILE_BYTECODE=1 \
    HF_HOME=/models \
    HF_HUB_DISABLE_SYMLINKS_WARNING=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

# ffmpeg: descargas, miniaturas y exportar · git: DeepFilterNet lo pide al cargar
# Node: el desafío JS de YouTube (yt-dlp)
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates tini git \
 && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=node /usr/local/bin/node /usr/local/bin/node

WORKDIR /app

# 1. motor de voz en su propio entorno (vt/tts.py lo busca en .venvs/<motor>/bin/python)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv -p 3.11 .venvs/omnivoice \
 && uv pip install -p .venvs/omnivoice/bin/python --torch-backend=cu128 omnivoice deepfilternet soundfile

# 2. servidor: los wheels nvidia-* de requirements.txt sobran, la imagen ya trae CUDA y cuDNN
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv -p 3.12 /opt/venv \
 && grep -v '^nvidia-' requirements.txt > /tmp/req.txt \
 && uv pip install -p /opt/venv/bin/python -r /tmp/req.txt

# 3. código (data/ y los modelos van en volúmenes)
COPY run.py ./
COPY vt ./vt
COPY web ./web

VOLUME ["/app/data", "/models"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=15m --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/', timeout=4)" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "python", "run.py"]
CMD ["--host", "0.0.0.0", "--no-browser"]
