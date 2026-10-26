# Cambios

Todos los cambios importantes de Translay. El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y las versiones, [Versionado semántico](https://semver.org/lang/es/).

Cada cambio que llega a `main` se anota primero en **Sin publicar**; al liberar una versión, `scripts/release.py` mueve esa sección a la versión nueva.

## Sin publicar

### Agregado

- Barra lateral también en el reproductor (se pliega a íconos con el botón junto al logo).
- «Bajar video» en la barra del reproductor y en el clic derecho para videos con solo audio.
- Los botones que trabajan muestran su avance: «Bajando video 42 %», «Exportando 63 %».

### Cambiado

- Lo que se edita (bibliotecas, colecciones, comentarios, personas) se ve al instante en todos lados, sin esperar al servidor.
- Las flechas de las filas del inicio quedan dentro de la fila y solo aparecen si hay más videos hacia ese lado.

### Arreglado

- «Editar» y «Otro patrón» de una biblioteca funcionan ahí mismo, sin llevar al inicio.
- Los menús ya no se cierran solos cuando algo se desplaza por su cuenta, y las opciones que abren otro panel ya no lo cierran en el mismo clic.
- Al recargar no aparece por un instante «Traduce tu primer video» ni el banner del canal roto.

## 1.0.0 · 2026-10-25

Primera versión pública.

### Traducción y doblaje

- Reconocimiento con Whisper large-v3-turbo en streaming, con VAD y acuerdo local propios.
- Traducción con Opus-MT big (fp16) y capas propias para español latinoamericano: división por oraciones, modismos y giros literales. NLLB-1.3B y MADLAD-3B como alternativas (`--translator`).
- Diarización propia (WeSpeaker en ONNX + agrupamiento incremental): 97.6 % de frases con la persona correcta en 12 videos de prueba.
- Doblaje con la voz clonada de cada persona (OmniVoice), referencias de hasta 8 s limpiadas con DeepFilterNet si tienen ruido, duración ajustada al espacio de cada frase y WSOLA de respaldo.
- Procesamiento adelantado: la voz suena sincronizada con la imagen (desfase mediano 0.08 s; 0.25 s en un video de 28 min).
- Persistencia por huella del video: lo procesado no se vuelve a procesar; si cambia el texto, la persona o el motor, la frase se vuelve a doblar sola.

### Biblioteca

- Portada con «Seguir viendo» y filas por colección; colecciones automáticas (Recientes, Todos, canales y categorías de YouTube) y propias.
- Varias bibliotecas, cada una en su carpeta (otro disco, por ejemplo), con sus videos, colecciones, glosario, personas, tema y modo de importar; «Mover a…» lleva los archivos.
- Banners y distintivos con patrones Bauhaus por colección y biblioteca; avatar y banner reales de los canales.
- Búsqueda en todas las transcripciones (inglés, español y comentarios, sin importar tildes).
- Selección múltiple para abrir, procesar, exportar, mover o eliminar.

### Importar y cola

- Enlaces de YouTube, playlists, varios enlaces a la vez, CSV con miles de enlaces y archivos del equipo; importar directo a una colección.
- Una sola cola en el servidor que sobrevive a recargar: el video que ves va primero y sigue tus saltos; «Priorizar», pausa y pantalla propia con estados.
- Descargas espaciadas y en orden o al azar, solo audio o video, «Solo descargar»; pausa automática si YouTube pide verificación y reintentos espaciados.
- Sesión de YouTube con cookies.txt o desde el navegador instalado.
- Modo reposo: los modelos dejan la GPU a los 45 s sin uso y el proceso de voz se cierra a los 2 min.

### Reproductor

- Vista ampliada y dividida, controles propios, velocidad de 0.75× a 2× sin cambiar el tono, subtítulos ES/EN.
- Indicador «Preparando NN % / Listo para reproducir» según la velocidad real del doblaje; pausa hasta que esté listo y reproducción automática del siguiente.
- Transcripción alineada EN | ES con la persona que habla, comentarios por frase y marcas en la línea de avance.
- Personas: nombre y voz de cada una (la suya clonada o la de otra persona del video).
- Glosario por biblioteca: términos fijos o sin traducir; al cambiarlo se re-traduce y se rehace la voz.

### Exportar

- Video traducido (voz en español + inglés como segunda pista + subtítulos), audio traducido, video y audio originales, subtítulos SRT en ambos idiomas y transcripción TXT; varios en un .zip.

### Acceso e integraciones

- Dueño sin sesión desde el mismo equipo y con contraseña desde otros; cada biblioteca privada, con contraseña o pública, de solo ver o ver e importar.
- Acceso desde otros equipos de la red local.
- API REST `/api/v1` con claves por biblioteca (lectura o escritura).
- Webhooks firmados con HMAC-SHA256, con reintentos y 21 eventos.

### Interfaz

- Diseño «Translay»: una sola fuente, claro y oscuro grafito, menús, listas y casillas propios, menú contextual por zona, barra lateral colapsable y silueta al cargar.
- La dirección guarda dónde estás: recargar no vuelve al inicio y atrás/adelante funcionan.

### Instalación y documentación

- Imagen Docker con CUDA 12.8, servidor y motor de voz; `docker-compose.yml` y `--owner-password` / `TRANSLAY_OWNER_PASSWORD` para el acceso del dueño en el contenedor.
- Documentación en Starlight (`docs/`) con referencia generada desde el código.
- Convención de commits (Conventional Commits) con validación en `.githooks/commit-msg`.
