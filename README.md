# Traductor de video EN → ES

Herramienta local que transcribe, traduce y **dobla al español con la voz de cada persona** un video en inglés. Vista de dos paneles: video original con subtítulos en inglés (izquierda) y video con subtítulos y voz en español (derecha), más la transcripción alineada EN | ES con la persona que habla.

**Estado:** fase 1 (texto + persistencia), fase 2 (traducción) y fase 3 (voz en español) terminadas.

## Uso

```bash
python run.py
```

Se abre `http://127.0.0.1:8765`. "Abrir video" (o arrastrar un archivo) y reproducir. Para YouTube, pegar el enlace en el campo de la barra (o en cualquier parte de la página, o abrir `http://127.0.0.1:8765/?yt=<enlace o id>`): el servidor lo descarga con yt-dlp a `data/youtube/` (MP4 hasta 720p + pista de audio aparte) y se procesa igual que un archivo local; la segunda vez abre al instante. El botón de la barra alterna entre "Escuchar original" y "Escuchar en español" (el original queda de fondo bajo la voz doblada).

Opciones: `--voice omnivoice|chatterbox|none`, `--translator opus-big|nllb-1.3b|madlad-3b|none`, `--model small.en`, `--device cpu --compute-type int8`, `--port`, `--no-browser`.

Requisitos: Python 3.11+ (`pip install -r requirements.txt`) y GPU NVIDIA (probado en RTX 4060 8 GB). El motor de voz vive en su propio entorno:

```bash
uv venv -p 3.11 .venvs/omnivoice
uv pip install -p .venvs/omnivoice/Scripts/python.exe --torch-backend=cu128 omnivoice deepfilternet soundfile
```

### Biblioteca y colecciones

Al abrir la herramienta se ve la **Biblioteca**: tarjetas con miniatura, nombre, duración, avance y botón "Ver" (retoma donde quedaste).

- **Recientes** (automática): todos los videos traducidos, del último abierto al primero.
- **Canales** y **categorías** (automáticas): se arman solas con los videos de YouTube (categorías en español).
- **Colecciones propias**: se crean en la biblioteca o desde "Guardar en…" en el reproductor; al traducir un video nuevo ese panel se abre solo para elegir dónde guardarlo.
- Los archivos locales se copian a `data/library/` en segundo plano (con su miniatura) para poder volver a verlos desde la biblioteca. Todo se guarda en `data/library.json`.

### Vista ampliada y vista dividida

Por defecto el video se ve **ampliado**: un solo video grande (subtítulo en español abajo, inglés pequeño arriba) y la transcripción al costado. "Ver dividido" vuelve a los dos paneles EN | ES; la elección se recuerda.

### Cola y modo reposo

- **Todo se procesa en una sola cola, en el servidor** (`vt/processor.py`): el video que estás viendo va primero, empieza desde tu punto de reproducción y, si saltas a una parte sin terminar, el procesamiento salta contigo. Al volver a la biblioteca sigue procesándose como una descarga. Los archivos recién abiertos que aún no tienen copia en el servidor los procesa el navegador como antes.
- **Botón "Cola"** (como las descargas del navegador): lo que se procesa ahora ("viendo" si es el video abierto), lo que espera y lo terminado, con avance, "Ver", "Quitar", "Pausar" / "Reanudar" y "Limpiar terminados". "Procesar" en una tarjeta de la biblioteca agrega un video a la cola. Pausar detiene los trabajos de fondo; el video que estás viendo se sigue procesando.
- Si un tramo ya reconocido quedó sin traducción o sin voz (un procesamiento que se cortó), la cola lo completa al pasar por ahí, empezando por lo que vas a escuchar.
- **Modo reposo:** los modelos ocupan la GPU solo mientras se procesa algo. A los 45 s sin uso pasan a la RAM (vuelven en ~1 s); a los 2 min, o al pausar la cola sin nada a la vista, se cierra el proceso de voz y la GPU queda como sin el servidor. Al abrir un video los modelos empiezan a cargar de inmediato (la voz tarda ~15 s desde el reposo profundo).
- **Turnos en la GPU:** reconocimiento, traducción y voz calculan por turnos, en orden de llegada (sus picos de memoria sumados desbordaban la GPU; con un candado común la voz quedaba relegada).
- **Referencias de voz de hasta 8 s:** con una referencia de 15 s la clonación tardaba 61 s por frase cuando Whisper ocupa la GPU (9 s → 4 s).
- **Memoria de GPU:** Whisper, el traductor y la voz comparten 8 GB. Los cachés de memoria de CTranslate2 (400 MB) y de torch (2.5 GB) están limitados: sin eso la GPU se llenaba, Windows desbordaba a memoria compartida y una frase podía tardar 65 s en vez de 1–2 s. Procesando ocupa ~5.6 GB.

### Preferencias

"Preferencias" en la barra: vista (ampliada / dividida), con qué audio abrir los videos, volumen del original bajo la voz en español, subtítulos en español e inglés, y cuándo mostrar el indicador de reproducción. Se guardan en el servidor (`data/prefs.json`) y valen para todas las pestañas. Para agregar una preferencia nueva basta sumar una entrada a `SCHEMA` en `vt/prefs.py` (el panel se arma solo) y leerla en la vista.

### Si YouTube pide verificar que no eres un bot

Tras muchas descargas seguidas YouTube puede bloquear la IP por unas horas. Para descargar con tu sesión, en Preferencias → «Importar sesión de YouTube»:

- **Subir cookies.txt** (recomendado en Windows): con la sesión de YouTube iniciada en tu navegador, exporta las cookies de youtube.com con una extensión como «Get cookies.txt LOCALLY» y súbelas con este botón. Funciona con el navegador abierto. Si las cookies vencen, se vuelven a exportar y subir.
- **Importar de {navegador}**: aparece un botón por cada navegador instalado. Firefox se puede leer abierto; Brave, Chrome y Edge bloquean sus cookies mientras están abiertos (ciérralos antes) y las versiones recientes las cifran.

Al importar, «Sesión de YouTube» pasa sola a «Archivo cookies.txt». Solo se guardan las cookies de YouTube y Google.

El archivo queda solo en tu equipo (`data/` no entra en git).

### Descargas de YouTube

En la barra y en el panel de la cola se ve cada etapa: Buscando → Video (con %) → Audio (con %) → Uniendo → Preparando.

### Cuándo reproducir

Sobre el video aparece "Preparando NN %" hasta que conviene reproducir y luego "Listo para reproducir". El indicador compara lo ya doblado por delante del punto de reproducción con la velocidad real del procesamiento, medida en **segundos de voz doblados por segundo** (una intro sin voz se procesa al instante y, medida en segundos de video, daba un "listo" falso). Para lo que viene asume al menos 70 % de voz, no promete nada hasta medir 8 s, y tiene histéresis para no parpadear.

## Cómo funciona

```
navegador                                    servidor (Python 3.14, asyncio)            proceso de voz (.venvs/omnivoice)
─────────                                    ───────────────────────────────            ─────────────────────────────────
archivo ─ decodeAudioData (16 kHz) ─────────► httpws.py     HTTP + WebSocket propios    tts_worker.py  OmniVoice (clonación)
  bloques de 1.5 s por delante de la         session.py    colas: ASR / voz              enhance_df.py  DeepFilterNet (limpia
  reproducción, al ritmo del servidor        streaming.py  búfer + acuerdo local                        referencias ruidosas)
<video> ─ capture-worklet.js (respaldo)      asr.py        Whisper large-v3-turbo      ◄─ ipc.py: tramas por stdin/stdout
                                             translate.py  Opus-MT big + textproc.py
voces ◄─ /audio/<video>/<frase>.wav ◄─────── speakers.py   diarización propia (WeSpeaker ONNX)
  suenan en el momento de cada frase         dub.py        voz por frase + ajuste de duración
                                             audiofx.py    WSOLA, re-muestreo, realce, YIN, ruido
                                             store.py      data/transcripts/<huella>.json
                                             youtube.py    descarga con yt-dlp (+ Node), miniatura y categorías
                                             library.py    biblioteca y colecciones (data/library.json)
                                             processor.py  cola en segundo plano (data/queue.json)
                                             resources.py  modo reposo: modelos a la RAM / proceso de voz cerrado
```

- **Procesamiento adelantado:** el navegador decodifica la pista de audio del archivo y la envía por delante de la reproducción (un bloque por cada confirmación del servidor, ~3× tiempo real). Cuando el video llega a una frase, su subtítulo, traducción y voz ya están listos: la voz suena **sincronizada** (desfase mediano medido 0.08 s). Si un archivo no se puede decodificar, se usa la captura mientras se reproduce (modo intérprete: la voz llega 2–5 s después).
- **Videos largos:** la voz va detrás del reconocimiento por pocas frases (comparten la GPU; bloques de 3 s); al saltar, las voces encargadas que aún no empezaron se cancelan. Cada frase se ajusta al espacio real hasta la siguiente (ritmo hasta ~20 caracteres/s y, si no cabe, WSOLA hasta ×1.25). Probado con un video de YouTube de 28 min: desfase mediano 0.25 s.
- **Diarización propia** (`vt/speakers.py`): huella de voz por frase (fbank tipo Kaldi propio + WeSpeaker ResNet34 en ONNX, ~10 ms), agrupamiento incremental por similitud coseno. Las frases cortas (< 1.6 s) dan huellas poco fiables: no crean personas ni mueven centroides, y se re-asignan cuando las huellas maduran (la frase se vuelve a doblar con la voz correcta).
- **Voz de cada persona:** sus mejores fragmentos originales (largos y limpios, hasta 9 s) forman su referencia; OmniVoice clona esa voz en español. Si la referencia es ruidosa (SNR < 20 dB) se limpia con DeepFilterNet antes de clonar.
- **Duración:** se le pide al motor la duración de la frase original (+10 %, sin bajar de ~17 caracteres/s), así el español calza en su espacio sin deformarse; WSOLA propio queda de respaldo (hasta ×1.3). Sonoridad igualada a la voz original.
- **Persistencia:** transcripción, traducción, personas, referencias de voz y audio doblado se guardan por huella de contenido del video. Al retroceder o reabrir, todo sale del disco; solo se procesa lo nuevo. Si cambia el texto, el motor o la persona de una frase, se vuelve a doblar sola.
- **Traducción:** Opus-MT big con capas propias (`vt/textproc.py`): división por oraciones, reescritura de modismos y giros literales, respeto de fragmentos y convenciones latinoamericanas.
- **Subtítulos:** máximo 2 líneas, repartidos por tiempo en las frases largas.

## Herramientas

| | |
|---|---|
| `tools/dub_file.py <video>` | Dobla un video completo sin navegador y exporta `<nombre>.es.mp4`; reporta persona por frase, compresión, retraso en vivo y diarización. |
| `tools/eval_tts.py` | Compara motores de voz con métricas objetivas: parecido de voz (WeSpeaker), identidad, inteligibilidad (Whisper en español), tono (YIN), velocidad y duración. Genera primero con el motor solo en la GPU y puntúa después. |
| `tools/eval_pipeline.py` | Reconocimiento (WER) y diarización contra la verdad de referencia; barre umbrales. |
| `tools/make_dialogue.py` | Diálogos de prueba multi-voz con Kokoro (`.venvs/kokoro`) + variantes con ruido (cafetería, música, rosa, zumbido) y su verdad de referencia. |
| `tools/eval_translation.py` | Compara traductores en 39 frases típicas de video. |
| `tools/transcribe_file.py` | Simula la reproducción en vivo e imprime frases, traducción, retraso y RTF. |
| `tests/test_core.py` | Pruebas sin GPU: streaming, almacenamiento, texto, audio (WSOLA, re-muestreo, tono) y diarización. |

### Elección del motor de voz (RTX 4060, 3 diálogos, 9 personas, 18 frases)

| motor | parecido de voz | identidad | error de palabras | RTF |
|---|---|---|---|---|
| **OmniVoice** (16 pasos, duración fijada) | **0.78** | 100 % | **2.2 %** | **0.27** |
| Chatterbox Multilingual | 0.64 | 100 % | 17.2 % (corta frases) | 0.83 |
| VoxCPM2 | 0.02 | 28 % | 99 % (alucina) | — |

Como referencia, dos grabaciones de la misma persona dan ~0.6–0.7 de parecido y personas distintas ≤ 0.2. Con ruido en el video: música 10 dB → 0.76; cafetería 10 dB → 0.66; ruido rosa 5 dB → 0.59 (0.45 sin DeepFilterNet).

### Diarización (12 videos: 2, 3 y 4 personas × limpio / cafetería / música / rosa)

97.6 % de frases con la persona correcta; WER del reconocimiento 0.6–9.4 % según el ruido.

### Elección del traductor

| modelo | mediana | notas |
|---|---|---|
| **opus-big** (fp16) | 52 ms | Elegido. Español latino natural. Cuantizado a int8 empeora. |
| nllb-1.3b (int8) | 347 ms | Natural en giros, pero con errores propios ("darme un like", usted). |
| madlad-3b (int8) | 557 ms | Calidad similar, 10× más lento. |

## Próximas fases

1. **Exportar desde la vista** — el MP4 doblado y subtítulos `.srt` en ambos idiomas (ya existe en `tools/dub_file.py`).
2. **Separar música y voz** del original para dejar el fondo intacto bajo el doblaje (hoy el original queda atenuado).
3. VAD neuronal en lugar del de energía.
