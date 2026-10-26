# Cambios

Todos los cambios importantes de Translay. El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y las versiones, [Versionado semántico](https://semver.org/lang/es/).

Cada cambio que llega a `main` se anota primero en **Sin publicar**; al liberar una versión, `scripts/release.py` mueve esa sección a la versión nueva.

## Sin publicar

### Corregido

- Crear, renombrar o eliminar una biblioteca fallaba al avisar a los webhooks y la pestaña no se actualizaba.
- El id (y el enlace `/b/<id>`) de una biblioteca con tildes o eñes ya no se rompe: «Océanos» es `oceanos`, no `oc-anos`.
- «Editar» y «Otro patrón» de una biblioteca funcionan ahí mismo, sin llevar al inicio.
- Los menús ya no se cierran solos cuando algo se desplaza por su cuenta, y las opciones que abren otro panel ya no lo cierran en el mismo clic.
- Al recargar no aparece por un instante «Traduce tu primer video» ni el banner roto de un canal.
- El aviso «Listo para reproducir» ya no tapa el subtítulo en inglés.
- La cola ya no reemplaza frases ya dobladas por fragmentos al retomar un video desde otro punto, ni pierde texto en la segunda pasada.
- Dos partes de Translay que abrían la misma transcripción a la vez podían quedarse con copias distintas y perder frases guardadas.
- Una frase cuya voz falla ya no deja el video entero en «error»: queda sin voz y se reintenta.
- Si el proceso de voz se cuelga, se cierra a los 5 min en vez de trabar la GPU para siempre; si no carga, se reinicia limpio.
- El reposo ligero libera la VRAM también con Chatterbox y VoxCPM, y un error al dormir los modelos ya no deja el estado en «cargando».
- Al fusionar dos personas, la voz clonada ya no se pierde (sobre todo al reabrir el video).
- Las frases muy largas sin puntuación ya no cortan el audio de su voz de referencia.
- El audio de un video terminado no se queda en memoria.
- Biblioteca, voces y personas se guardan sin poder quedar a medias, con una copia de respaldo (`.bak`) que se usa si el archivo se daña.
- «Mover a…» otra biblioteca devuelve los archivos si alguno está en uso, en vez de dejar el video partido.
- Desde otro equipo de la red (http) ya se puede reproducir con voz e importar archivos.
- Los primeros mensajes del servidor ya no se pierden en conexiones lentas (el invitado veía la interfaz del dueño).
- Al reconectar (o tras «Reiniciar ahora»), el video que ves vuelve a tener prioridad en la cola.
- Enter en los cuadros de texto de los diálogos acepta en vez de cancelar.
- En Cola → Exportaciones, «Descargar» y «Cancelar» funcionan; en el panel, el botón de quitar una exportación se ve.
- Borrar el video que suena en miniatura cierra la miniatura.
- Pasar rápido entre videos ya no aplica la posición ni la duración de uno al otro.
- Cancelar «Importar» desde una colección ya no deja esa colección elegida para la próxima importación.
- Un invitado ya no puede abrir Preferencias por la URL (salían avisos de permiso en bucle).
- Reproducir a otra velocidad ya no acumula audio en memoria.
- Lo que se escribe en Preferencias (una contraseña, una URL) ya no se borra si llega un aviso de otra pestaña.
- En el celular hay botón para crear una colección.
- Eliminar la biblioteca abierta cierra el video que se estaba viendo de ella.
- Los toasts de Acceso ya no dicen «Copiado copiado».
- Los avatares y banners de canales se bajan aparte y de a uno: ya no ocupan las conexiones del navegador (el video no cargaba) ni disparan el límite de YouTube.

### Seguridad

- Otro sitio abierto en el navegador ya no puede usar Translay como el dueño: el WebSocket y los pedidos que cambian algo exigen que el `Origin` sea la propia app (`--allow-origin` / `TRANSLAY_ORIGINS` para proxies que cambian el Host).
- `GET /api/v1/exports/{id}` solo muestra exportaciones de videos que se pueden ver.
- Al volver una biblioteca a «con contraseña», las sesiones de antes ya no reviven.
- Revisión de todo el código: los videos ya no pueden registrar rutas de archivos (solo título, duración y origen); las rutas de archivos de los videos nunca salen de su carpeta.
- Las subidas solo aceptan video o audio (y la miniatura, JPEG de hasta 2 MB); una subida cortada no deja el archivo a medias.
- Los archivos de las bibliotecas se sirven siempre como medios o descargas, nunca como páginas, con `X-Content-Type-Options: nosniff`.
- «Desde este equipo» solo vale si el pedido llega a `localhost`/`127.0.0.1` (protección contra *DNS rebinding*).
- Iniciar sesión siempre da un token nuevo (fijación de sesión), con un máximo de 10 intentos fallidos cada 10 minutos por equipo; el hash de la contraseña ya no frena al servidor.
- Importar o ver un video exige permiso en la biblioteca de ese video, no en la abierta.
- WebSocket: marcos sin máscara, de control demasiado largos o mensajes que superan 16 MB entre fragmentos cierran la conexión; las cabeceras HTTP tienen un máximo de 100 y 15 s para llegar.
- Los avatares de canales (`/chan/`) piden acceso como el resto de las miniaturas.

### Agregado

- **Rendimiento** (Preferencias): detecta GPU, VRAM, RAM y CPU y elige un perfil de modelos (Máxima calidad, Equilibrado, Ligero, Solo subtítulos, Subtítulos ligeros) con velocidades medidas en equipos de 8, 6, 4 y 2 GB y sin GPU. Muestra si cada perfil va bien, al límite o forzado, cuánto tarda un video y si se puede ver en vivo; cambiar de perfil reinicia Translay solo.
- Límites de VRAM, RAM e hilos de CPU para Translay; la RAM y la CPU se aplican al momento (Job Object de Windows, sin administrador).
- Avisos de por qué algo va lento: perfil forzado, VRAM que desborda a memoria compartida, poca RAM, límites demasiado bajos, otro programa en la GPU.
- **Papelera**: eliminar videos, vaciar o eliminar una biblioteca los guarda 30 días; «Deshacer» en el aviso y Preferencias › Papelera para restaurar o borrar para siempre.
- Labs de hardware (`tools/lab/`) que emulan equipos menores con límites reales de VRAM, RAM y CPU, y `vt/hardware.py` para detectar el equipo.
- Barra lateral también en el reproductor (se pliega a íconos con el botón junto al logo).
- «Bajar video» en la barra del reproductor y en el clic derecho para videos con solo audio.
- Los botones que trabajan muestran su avance: «Bajando video 42 %», «Exportando 63 %».

### Cambiado

- Vaciar y eliminar una biblioteca piden escribir su nombre; «Vaciar…» pasó de la cabecera de «Todos» al menú «⋯» de la biblioteca.
- `--model`, `--compute-type`, `--beam`, `--translator`, `--voice` y `--device` ya no tienen valor fijo: sin ellos, los decide el perfil de rendimiento.
- Lo que se edita (bibliotecas, colecciones, comentarios, personas) se ve al instante en todos lados, sin esperar al servidor.
- Las flechas de las filas del inicio quedan dentro de la fila y solo aparecen si hay más videos hacia ese lado.

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
