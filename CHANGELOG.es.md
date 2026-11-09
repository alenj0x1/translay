# Cambios

Todos los cambios importantes de Translay. El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y las versiones, [Versionado semántico](https://semver.org/lang/es/).

Las mismas entradas en inglés: [CHANGELOG.md](https://github.com/alenj0x1/translay/blob/main/CHANGELOG.md). Los cambios que esperan la próxima versión van en **Sin publicar**, arriba (esa sección solo existe mientras haya alguno y la documentación no la muestra); `scripts/release.py` la convierte en la versión nueva.

## 1.11.0 · 2026-11-08

### Agregado

- Preferencias › Apariencia: «Color de énfasis» elige el color de los botones, el avance y la reproducción (el del tema o uno de siete); «Color de cada biblioteca» ahora lo reemplaza solo cuando está activado.

### Corregido

- Agregar un enlace: presionar Enter con algo que no es un enlace de YouTube ni de Dropbox muestra un aviso en vez de no hacer nada, y un video que no se puede descargar (privado, eliminado, solo para miembros, con restricción de edad o un enlace que pide cuenta) pasa a «Con error» al instante con un aviso que dice cuál y por qué, en vez de reintentar en silencio durante 20 minutos.
- App de escritorio: el porcentaje de la instalación y de la descarga de modelos sigue lo que se escribe y se descarga en el momento; antes, las descargas Xet de Hugging Face dejaban la carpeta en 0 MB hasta el final y Windows listaba los archivos que se estaban escribiendo con su tamaño viejo, así que la barra se quedaba quieta y luego saltaba.
- Los paneles de la Cola y de «Agregar» se cierran al tocar cualquier cosa fuera de ellos, también el otro botón (algunos elementos detenían el clic y el panel seguía abierto).
- Grabar pantalla: al elegir una ventana o una pestaña, Translay sigue al frente en vez de quedar detrás, y el cuadro avisa que una ventana o la pantalla completa graban el sonido de todo el equipo (también una llamada).
- Resumen: «Resumir» aparece apenas termina la transcripción, sin salir del video y volver; si el video abierto ya tiene frases en el servidor que la pestaña no recibió, se vuelve a pedir la transcripción.
- Biblioteca: elegir videos en el inicio muestra las acciones de la selección (no aparecían), y en el celular quedan bajo el encabezado aunque bajes mucho; el clic derecho sobre la casilla de una tarjeta abre el menú del video.
- Preferencias › Rendimiento: un nombre de procesador largo («AMD Ryzen 7 7730U with Radeon Graphics») usa dos líneas en vez de salirse de su tarjeta.

## 1.10.0 · 2026-11-08

### Agregado

- Resumen del video: la pestaña «Resumen» cuenta de qué se trató el video y enumera todos sus puntos importantes, cada uno con su minuto (un clic salta ahí); no hay un número fijo de puntos, un video largo tiene más. Se hace en tu equipo con un modelo de lenguaje pequeño (Qwen3 4B, 1.7B o 0.6B, elegido según tu equipo o en Preferencias › Resumen) y sale en español sea cual sea el idioma del video. «Resumir» lo hace cuando lo pides, o cada video se resume cuando la cola lo termina. La API tiene `GET` y `POST /api/v1/videos/{id}/summary`, y los webhooks reciben `resumen.listo` y `resumen.error`.
- Exportar: «Texto en español», «Texto del original» y «Resumen» como archivos TXT.
- Exportar: en este equipo, Translay pregunta dónde guardar con el cuadro de Windows («Guardar como» con el nombre propuesto, o una carpeta si son varios archivos), empezando en la última carpeta que usaste; en Preferencias › Exportar se puede dejar una carpeta fija. Cada exportación de la lista de la Cola muestra dónde se guardó, su menú del clic derecho tiene «Mostrar en el Explorador» y «Copiar la ruta», y lo guardado en una carpeta sigue en la lista después de reiniciar.
- Biblioteca: cada tarjeta muestra el idioma en que se habla en el video (EN, PT, ES…) junto a su duración.

### Arreglado

- Encabezado en el celular: el botón de la biblioteca ya no se encima al logo, «Agregar» queda solo con su ícono en pantallas angostas (la regla apuntaba a un marcado viejo) y ningún botón baja a otra fila a 320 px; se quitó la línea gris bajo el encabezado.
- Reproductor: las esquinas redondeadas ya no muestran una línea negra bajo los controles claros.

## 1.9.0 · 2026-11-02

### Agregado

- Exportar: elegir la calidad del audio («Alta», «Media» o «Liviana», esta en mono) y Opus como tercer formato, además de M4A y MP3; el diálogo muestra cuánto va a pesar. Los videos se pueden exportar en 480p o 360p. La API acepta `"quality"` y `"video"`.
- Exportar: «Guardar en» guarda directo en una carpeta de este equipo, también en otro disco, sin pasar por el disco de los datos ni dejar una segunda copia, y varios archivos van sueltos en carpetas en vez de un `.zip` (listos para un pendrive); «Mostrar en la carpeta» la abre en el Explorador. La API acepta `"dest"` (solo el dueño, desde este equipo).
- Preferencias › Almacenamiento: cuánto ocupan las descargas, los modelos, la voz en español, la papelera y lo demás, con el espacio libre de cada disco; libera las descargas que nunca se tradujeron, las más pesadas una por una, los modelos (cada uno con para qué sirve, qué perfiles lo usan y cuándo se usó por última vez), los archivos sueltos, la papelera, las exportaciones y la caché de instalación de la app de escritorio.
- Perfiles y modelos: el instalador de la app de escritorio pide el perfil después de instalar el servidor (con el recomendado marcado y cuánto descarga cada uno), instala el motor de voz solo si el perfil lo usa y baja sus modelos, así Translay abre listo. Al elegir otro perfil se dice qué modelos faltan y cuánto pesan antes de reiniciar, se bajan al reiniciar (y la app instala el motor de voz si hace falta) y se pueden borrar los que el perfil nuevo no usa.

### Arreglado

- Las exportaciones para descargar ya no quedan en el disco hasta reiniciar: se borran al quitarlas del panel «Cola», a las 24 horas con el servidor andando y al momento si fallan. Los `.tmp` de una escritura interrumpida se borran al arrancar.

## 1.8.0 · 2026-11-02

### Agregado

- Exportar varios videos: el `.zip` usa carpetas como el aside. Desde un canal, colección, playlist o categoría, todo va en una carpeta con su nombre; desde «Todos», «Recientes» o una búsqueda, «Carpetas» elige una carpeta por canal (la de siempre), colección o playlist, o ninguna. La API acepta `"layout"` y `"folder"`.

## 1.7.1 · 2026-11-01

### Cambiado

- App de escritorio: las versiones nuevas se avisan en vez de instalarlas la app: «Descargar» abre el instalador en tu navegador y lo ejecutas como siempre. El análisis por aprendizaje automático de Windows Defender confundía con un troyano la versión que bajaba y ejecutaba su propio instalador, y la borraba.

### Corregido

- Sitio de documentación: el botón de menú solo aparece en el celular, con un solo ícono (tres líneas cerrado, X abierto) y con espacio junto al selector de idioma; el índice de la derecha es más angosto.
- Sitio de documentación: los bloques de código con barra de terminal o de título se unen a ella sin esquinas redondeadas en medio, y las tablas de dos columnas sin títulos ya no muestran una primera fila vacía.

## 1.7.0 · 2026-11-01

### Agregado

- App de escritorio: Translay se actualiza solo. Busca versiones nuevas en GitHub al abrir y cada 6 horas (Preferencias › App de escritorio › «Buscar actualizaciones»: automáticamente o solo a mano), muestra las notas e instala con «Actualizar a» con la versión nueva, y vuelve a abrirse. Espera a que terminen la cola, las descargas y las exportaciones, y solo instala actualizaciones firmadas con la clave de Translay.
- Portugués → español: los videos en portugués se traducen y doblan igual que los en inglés, con Opus-MT itc-itc (tan bueno como MADLAD-3B en el laboratorio y diez veces más rápido) y reglas que reescriben modismos y formas coloquiales de Brasil («pisou na bola», «pra», «tá») antes de traducir.
- Detección automática del idioma: los videos nuevos (enlaces, archivos y grabaciones de pantalla) no piden idioma; Whisper lo detecta con los primeros segundos de voz (100 % de aciertos en el laboratorio en inglés, portugués y español, también con ruido de fondo). Un idioma que Translay todavía no traduce solo se transcribe, en ese idioma.
- «Solo transcribir» para cualquier idioma: «Agregar ▾» › «Agregar y solo transcribir», o «Idioma y traducción» en el menú del video; pasar de traducir a transcribir no borra nada. La preferencia nueva «Solo transcribir lo que está en» (español, si no la cambias) decide qué idioma detectado solo se transcribe. La API acepta `"lang": "auto|en|pt|es"` y `"task": "translate|transcribe"` al importar.
- La búsqueda encuentra más que lo que se dice: el campo («Buscar videos y lo que se dice») agrupa los resultados en «Videos» (título o canal de los videos de la biblioteca, como tarjetas normales), «Colecciones y canales» (colecciones, playlists, categorías y canales por nombre; un clic la abre) y «En lo que se dice» (transcripciones, traducción y comentarios, como antes), con un conteo como «2 videos · 5 frases · 1 colección».
- Un traductor por idioma de origen: cada uno se carga la primera vez que llega un video en su idioma y solo uno está en la GPU a la vez, así la memoria no crece con los idiomas. El del portugués se prepara desde la publicación oficial de OPUS-MT (versión fija y SHA-256 verificado) la primera vez que hace falta, sin frenar otros videos.

### Cambiado

- «Subtítulos en inglés» ahora es «Subtítulos del original», en Preferencias y en Exportar: el SRT lleva el idioma del video en el nombre (`.pt.srt`) y el MP4 marca la pista original con su idioma real. Tu preferencia se conserva y la API sigue aceptando `srt_en`.
- Los perfiles de rendimiento dicen el nivel del traductor (`big` o `base`) en vez del nombre de un modelo, porque cada idioma tiene el suyo.
- «Agregar ▾» ofrece «Agregar y traducir» y «Agregar y solo transcribir» en lugar de «Está en español: solo transcribir»; el idioma siempre se detecta.
- «Importar» ahora es «Agregar», un botón dividido cuya parte principal hace lo que más usas en este navegador (desde 3 usos; si no, «Agregar»): pegar un enlace, «Subir» archivos, «Capturar» la pantalla o «Pegar enlaces». Su ▾ siempre abre el panel completo: el campo del enlace con «Agregar y traducir» / «Agregar y solo transcribir» y las tarjetas «Archivos», «Grabar pantalla» y «Varios enlaces». La preferencia nueva «Botón Agregar» (Preferencias › Agregar y descargar, antes «Importar y descargas») puede dejarlo siempre en «Agregar». Todo lo que agrega contenido también dice «Agregar» (cabeceras de colección, biblioteca vacía, menús contextuales, «Agregar varios enlaces»); «Importar sesión» y la ruta `import` y la clave `import_mode` de la API no cambian.

### Corregido

- App de escritorio: los botones de la ventana (minimizar, maximizar, cerrar) ya no se cortan en ventanas más angostas; la barra de título pasa antes a solo íconos y la búsqueda cede su lugar.
- El reconocimiento en vivo tiene reglas de cada idioma (palabras con las que una oración casi nunca termina y las frases que Whisper inventa sobre silencio, como «Subtítulos realizados por la comunidad de Amara.org»): antes solo existían las del inglés, así que los videos en español también salen con frases más limpias.

## 1.6.0 · 2026-11-01

### Agregado

- Grabar la pantalla («Importar › Grabar pantalla»): una pestaña, una ventana o toda la pantalla, completa o una zona. Al pasar el cursor por la vista previa se resaltan los recuadros que detecta (un video en reproducción, aunque ocupe parte de una página, ventanas y paneles); un clic elige, la rueda pasa al recuadro que lo contiene y arrastrar marca uno a mano. Calidad Alta, Media, Ligera o Solo audio y 30 o 15 cuadros, con el peso estimado por minuto y por hora. Se transcribe y traduce en vivo mientras se graba; luego se comprime (H.264 + AAC) y entra a la cola. Nada se pierde si se corta la conexión, se reinicia el servidor o se cierra la pestaña: cada segundo queda en el navegador hasta que el servidor lo confirma y la subida se retoma sola.

- Las listas vacías se explican solas con un ícono, un título y qué va a aparecer ahí (secciones de la Cola, Exportaciones y otras pantallas) en vez de una caja vacía o un «Nada aquí» suelto.

- Exportar el audio en MP3: al marcar el audio traducido o el original, «Formato del audio» deja elegir M4A o MP3 (192 kbps); el navegador lo recuerda. La API acepta `"audio": "mp3"`.

### Corregido

- Una exportación por lotes ya no falla entera por un video: si uno no se puede exportar (por ejemplo, lo borraron de YouTube y nunca se descargó), se omite, el resto sigue y el `.zip` trae `omitidos.txt` con el motivo. Los errores se muestran en palabras claras en vez del texto crudo de yt-dlp.
- Cuando parte de una colección no está descargada, el botón de su cabecera es «Exportar descargados (N)» y exporta solo lo que está en tu equipo; antes, «Exportar» exportaba la colección entera e intentaba bajar de YouTube lo que faltaba.
- Al exportar audio se ve el avance mientras se convierte cada archivo (un mix de dos horas tarda más de un minuto) y en lotes grandes el porcentaje va con un decimal y antes del título, así que el panel ya no parece trabado en 0 %.

### Rendimiento

- Las exportaciones convierten y mezclan varios videos a la vez (hasta seis, la mitad de los hilos del procesador): cerca de tres veces más rápido en un lote grande, p. ej. 8,6 horas de audio a MP3 en menos de dos minutos. Cada archivo entra al `.zip` apenas está listo y se borra su copia suelta, así que un lote ocupa su tamaño una vez en disco y no dos; una exportación cancelada borra lo que llevaba.

## 1.5.0 · 2026-11-01

### Agregado

- «Seleccionar descargados (N)» en la cabecera de una colección elige solo los videos que ya están en tu equipo, sin los que siguen en la cola, para exportarlos (por ejemplo, solo el audio) o moverlos.
- Conectar tu cuenta de YouTube: «Conectar con Brave» (o tu navegador predeterminado) abre una ventana con un perfil de navegador propio de Translay; inicias sesión una vez, la cierras y las descargas usan esa sesión. Se renueva sola antes de descargar si tiene más de una semana y cada vez que YouTube pide verificar que no eres un bot (la descarga se reintenta sin la pausa de 20 minutos). Sin extensiones, sin exportar `cookies.txt` y con tu navegador de siempre abierto.
- Cuando YouTube pide verificar que no eres un bot o un video tiene restricción de edad, el aviso ofrece «Conectar YouTube».

### Corregido

- Los videos importados por enlace que se quedaban con su id de YouTube como nombre reciben su título y canal: la búsqueda ahora corre en segundo plano en todas las bibliotecas, sigue tras reiniciar y reintenta cada hora (antes corría una sola vez y se perdía si Translay se cerraba o YouTube no respondía).
- En el celular, un grupo de opciones que no cabía en una línea quedaba como una píldora deforme: ahora muestra una opción por fila, y las preferencias con más de cuatro opciones («Sesión para descargar») usan una lista desplegable.
- En el celular, los botones del encabezado van en una sola fila (el de «Biblioteca» ya no baja solo a otra), y el encabezado y las píldoras de la barra lateral ya no se estiran en páginas con poco contenido.
- En modo oscuro, los interruptores usan el mismo gris que la opción elegida en vez de un tono casi blanco.
- El aviso con botón («Deshacer», «Conectar YouTube») ya no aprieta su texto en la mitad del ancho del celular.

### Seguridad

- La cuenta conectada guarda solo las cookies de youtube.com, cifradas con DPAPI, y se las pasa a yt-dlp en memoria (sin archivo en texto plano). Translay habla con el navegador por un canal privado, no por un puerto de red, solo le pide las cookies, nunca toca tu perfil de siempre y no guarda nada de la cuenta. «Desconectar» cierra la sesión en Google y borra el perfil.

## 1.4.0 · 2026-10-28

### Agregado

- Enlaces de Dropbox: pega el enlace compartido de un video (también dentro de una carpeta, como `dropbox.com/scl/fo/…/video.mp4`) en «Importar», en el cuadro de varios enlaces, en un CSV o por la API. Entra a la cola, se descarga con su avance igual que uno de YouTube y su tarjeta dice «Dropbox».
- Videos que ya están en español: «Importar ▾ › Está en español: solo transcribir», o «Idioma del video» en el menú contextual. Se transcriben en español sin traducir ni doblar, se reproducen con el audio original y un solo subtítulo, y la transcripción muestra una columna.
- «Renombrar…» en el menú contextual de un video le pone tu propio nombre (por ejemplo, en vez de `21_10`); se queda aunque el video se vuelva a descargar. También `PATCH /api/v1/videos/{id}` con `{"title"}`.
- La API de importar acepta `"lang": "es"`, y los datos de un video incluyen su `lang` y el `url` compartido.

### Cambiado

- Los perfiles ligeros («Ligero» y «Subtítulos ligeros») usan Whisper `small` en lugar de `small.en`, así también reconocen español.

### Corregido

- En el celular, el video del reproductor quedaba sin ancho y no se veía.

## 1.3.1 · 2026-10-27

### Cambiado

- Translay ahora tiene licencia MIT (`LICENSE`); el instalador la incluye.
- Los mensajes de commit siguen Conventional Commits en inglés, con un cuerpo que detalla cada cambio.

### Corregido

- La página de cambios de la documentación ya no muestra una sección «Sin publicar» vacía encima de la última versión (parecía no lanzada): solo lista versiones publicadas.

## 1.3.0 · 2026-10-27

### Agregado

- App de escritorio para Windows con instalador (`Translay_<versión>_x64-setup.exe`): se instala sin ser administrador, prepara sola el servidor y el motor de voz y abre Translay en su propia ventana.
- Pantalla «Preparar Translay»: tu GPU, si tendrás voz en español o solo subtítulos, dónde guardar la biblioteca y el avance de la instalación en el propio botón. Las versiones nuevas actualizan solas los paquetes que cambiaron.
- El instalador trae Python 3.12 y 3.11, ffmpeg, Node.js y uv verificados por SHA-256; los paquetes de Python se instalan fijados con su huella (`desktop/locks/`).
- Barra de título propia que sigue el tema, con Preferencias y el cambio entre claro y oscuro como íconos junto a minimizar, maximizar y cerrar. La pantalla de inicio abre con el último tema usado.
- Preferencias › App de escritorio: seguir en la bandeja al cerrar la ventana (la cola continúa y, al terminar, Translay se cierra y libera todo), cambiar la carpeta de la biblioteca Principal y abrir los registros.
- Cerrar la app cierra también el servidor y todo lo que lanzó (modelos, voz, descargas, ffmpeg), aunque se cierre de golpe: no queda nada usando la GPU ni la RAM.
- `--data-dir` (o `TRANSLAY_DATA`) elige la carpeta de datos, y `TRANSLAY_VENVS` la de los entornos de voz.
- Documentación en inglés y en español, con diagramas; README y changelog en los dos idiomas.

### Cambiado

- La fuente Plus Jakarta Sans la sirve el propio Translay: la interfaz se ve igual sin internet.

### Corregido

- Al cambiar entre claro y oscuro, los botones grises ya no parpadean.

## 1.2.0 · 2026-10-26

### Agregado

- Soporte para equipos con memoria unificada, como NVIDIA DGX Spark (GB10): la GPU se detecta con la RAM del sistema como memoria, así que Rendimiento ya no la trata como «sin GPU» (marcaba «Muy forzado» a 0,02×) y el perfil automático elige «Máxima calidad». Los equipos con GPU dedicada no cambian.
- Con memoria unificada, el reposo ligero se hace junto con el profundo: pasar los modelos a la RAM no liberaba nada.

## 1.1.0 · 2026-10-26

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
