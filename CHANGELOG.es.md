# Cambios

Todos los cambios importantes de Translay. El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y las versiones, [Versionado semántico](https://semver.org/lang/es/).

Las mismas entradas en inglés: [CHANGELOG.md](https://github.com/alenj0x1/translay/blob/main/CHANGELOG.md). Los cambios que esperan la próxima versión van en **Sin publicar**, arriba (esa sección solo existe mientras haya alguno y la documentación no la muestra); `scripts/release.py` la convierte en la versión nueva.

## Sin publicar

### Agregado

- Reproductor: la línea de avance muestra los capítulos del video (de su resumen) como tramos con un pequeño hueco entre ellos; al pasar el mouse se ve el nombre del capítulo sobre el tiempo, el capítulo actual aparece junto al tiempo y un resumen que llega mientras se mira los suma sin recargar.
- Videos en italiano: se detectan, transcriben, traducen al español y al portugués con Opus-MT itc-itc y al inglés con roa-eng (los modelos que ya usa el portugués, así que no hay nada nuevo que descargar) y se doblan; con las abreviaturas del italiano y los créditos de subtítulos que Whisper inventa sobre silencio («Sottotitoli creati dalla comunità Amara.org», «Sottotitoli a cura di QTSS»).
- Videos en japonés y coreano: se detectan, transcriben, traducen al español, al portugués y al inglés con MADLAD-400 3B (de 8 a 10 puntos de chrF sobre cada Opus-MT medido en FLEURS) y se doblan. Sus ~3 GB se descargan con el primer video en japonés o coreano, no con el perfil. Las oraciones japonesas se cortan tras 。！？ y en vivo se unen sin espacios, una pausa las cierra con 。, las coreanas se cortan sin pedir mayúscula, y se descartan las frases que Whisper escribe sobre silencio en cada idioma («ご視聴ありがとうございました», «다음 영상에서 만나요»).
- Grabar pantalla: «Silenciar las otras apps al grabar una ventana» (Ajustes › Agregar y descargar, apagada por defecto) silencia las demás aplicaciones mientras se graba una ventana en Windows 10, donde una ventana trae el sonido de todo el equipo, y les devuelve el sonido al terminar la grabación o si se cierra su pestaña.
- Ajustes › Rendimiento › **Guardar informe** escribe un informe de diagnóstico (versión, compilación de Windows, perfil y las últimas líneas de los registros) en Descargas, o lo descarga desde otro equipo; cada error deja ahora una línea en `app.log`, con hora y contexto.
- Doblaje: **Fondo sin la voz original** (Ajustes › Audio y subtítulos, activado por defecto): al terminar de doblar un video se separan su música y sus efectos de la voz original (CDX23, en el motor de voz), y el reproductor y la exportación ponen la voz doblada sobre ese fondo en vez del original bajado, así ya no se oye el idioma original debajo.
- Transcripción: editar la traducción de una frase ahí mismo (doble clic o clic derecho › **Editar traducción**). **Rehacer voz** la vuelve a doblar en tres tomas para escuchar y elegir; una frase corregida a mano conserva su texto aunque cambien el glosario o el traductor.

### Cambiado

- Inicio de sesión: **Volver** pasa arriba a la izquierda de la tarjeta, con una flecha, en vez de quedar entre la contraseña y las bibliotecas públicas.
- Grabar pantalla: en Windows 11, una ventana grabada trae solo el sonido de su aplicación, no el de todo el equipo (Windows 10 no puede separarlo, así que allí sigue como antes y el cuadro lo avisa).

### Corregido

- Las actualizaciones llegan a todos al instante detrás de un proxy que guarda los `.js` y `.css` (como «Cache Assets» de Nginx Proxy Manager): la página pide sus estilos y scripts con `?v=` y una huella de los archivos de la interfaz y del idioma (también el worker de las escenas y el `scenes.js` que carga). Antes el proxy seguía entregando la versión anterior durante horas.
- Agente: un invitado «Solo ver» ya no ve el chat, las sugerencias, **Encender** ni «Preguntar a Lumi», que el servidor le niega; la pestaña del agente explica que preguntarle es de quien puede importar. La barra del agente ya no muestra un «null» suelto a quien no es el dueño.
- Los invitados que solo pueden ver ya no reciben «No tienes permiso para esta acción en esta biblioteca» cada vez que abren un video: el reproductor solo le pide a la cola priorizar el video abierto (`watch`) cuando la biblioteca permite importar, y la sugerencia «Resumir» del agente no se les muestra.
- Agente en Linux y en Docker: el resumen, las descripciones cortas y las preguntas ya no fallan al intentar bajar el `llama-server` de Windows. La imagen de Docker compila `llama-server` con CUDA de la misma versión de llama.cpp, y fuera de Windows Translay usa el de `TRANSLAY_LLAMA_SERVER` o el del `PATH` (`LLAMA_CUDA_IMAGE` y `LLAMA_CUDA_ARCHITECTURES` lo compilan para una sola GPU, p. ej. GB10).

### Arreglado

- Grabar pantalla: una grabación ya no se pierde cuando su página no vuelve. Cada segundo lleva las opciones de la grabación y, si el servidor no recibe nada durante un minuto (se cerró la pestaña o la ventana que se grababa y después el navegador, se cerró la app, o se abrió Translay en otra dirección), arma lo que tiene y lo agrega a la biblioteca; si la página vuelve con los segundos que faltaban, el video se completa.
- App de escritorio: cerrar la ventana mientras se graba detiene y guarda la grabación antes, y Translay ya no se cierra desde la bandeja en medio de una grabación o de su subida.
- Invitados: un invitado «Solo ver» ya no recibe «No tienes permiso para esta acción en esta biblioteca» al abrir un video (la página pedía anotarlo en la biblioteca). La página ahora solo le pide al servidor lo que esa persona puede hacer.
- Invitados: un video que no está doblado entero ya no queda en pausa para un invitado «Solo ver» en «Se reanuda al estar listo 0 %». Como no se le procesa nada, escucha el original donde falta la voz y la barra lo dice.
- La página muestra el ícono de Translay en la pestaña del navegador (pedía `/favicon.ico` y recibía un error).
- Grabación de pantalla: una grabación ya no llena el disco. El servidor deja de recibirla cuando quedaría 1 GB libre (o a los 24 GB por grabación); lo demás espera en este equipo con **Sin espacio en el disco** y se sube cuando hay lugar.
- Videos en coreano: los créditos de subtítulos que Whisper escribe sobre la música con otras palabras («한글자막 제공 및 자막 제공 및…») y, en cualquier idioma, las frases que terminan con las mismas palabras repetidas tres veces ya no se muestran ni se doblan (solo con confianza baja, como las demás frases inventadas).
- App de escritorio: la ventana solo abre la dirección del servidor que lanzó (la de este equipo y el puerto que eligió), leída de la salida del servidor, nunca de sus errores.

## 1.14.0 · 2026-11-14

### Agregado

- App de escritorio: **Ver la bienvenida** (Ajustes › App de escritorio) muestra otra vez el asistente de primer uso sin reinstalar; solo se aplica lo que se cambie ahí.
- Idiomas: Translay en español, inglés y portugués. Una sola elección de idioma (Ajustes › Uso › Idioma, por defecto el del sistema; las instalaciones de antes quedan en español) para la interfaz, la traducción y la voz, el agente y los resúmenes; **Traducir a** lo separa para la traducción y el doblaje. Cambiar el idioma se aplica al instante, sin recargar la app.
- Idiomas: cada video guarda su traducción y su voz doblada por idioma. Al elegir otro idioma vuelve lo que ya estaba hecho en él, y lo que falta se traduce y dobla al abrir el video.
- Rutas de traducción medidas con FLEURS: inglés → portugués con Opus-MT tc-big en-pt, español → portugués con Opus-MT itc-itc, y español/portugués → inglés con Opus-MT tc-bible roa-eng, preparado desde la publicación oficial como itc-itc.
- Catálogos de la interfaz (web/i18n/*.json, con el texto en español como clave) para toda la app y los mensajes del servidor; `tools/i18n.py` lista lo que falta y una prueba exige catálogos completos.
- Agente: un personaje que armas tú, una estrella de puntas redondeadas con su forma, ojos, boca, mejillas y un accesorio (Ajustes › Agente › Avatar, con «Al azar»). Duerme con su modelo apagado, despierta mientras carga, piensa y habla al responder, y salta con corazones al tocarlo. Con el chat vacío está al centro con lo que sabe hacer debajo; con la primera pregunta vuela a su respuesta.
- Agente: las acciones rápidas (exportar, ir a un momento, subtítulos, guardar, avisos) entienden español, inglés y portugués y responden en el idioma de la app.
- Pantalla de Bibliotecas: la abierta destacada con su escena de caracteres y las demás en tarjetas compactas con su patrón en la esquina; el menú de bibliotecas también muestra el patrón de cada una.
- Exportar: un diálogo nuevo con la miniatura del video y tres tarjetas (Video, Audio, Texto) con sus opciones; el botón dice cuántos archivos se van a guardar.
- Un componente de carrusel para filas de opciones (de a cuatro, con flechas a los lados), usado primero por el creador del agente.
- Lab `tools/lab/lang_adherence.py`: cuántas veces cada modelo del agente responde en el idioma pedido.
- Ajustes: una página de inicio con una tarjeta por sección, en cinco bloques (General, Mirar, Videos, Bibliotecas y acceso, Equipo), y una búsqueda que también encuentra las opciones de dentro de cada sección; la barra lateral usa los mismos bloques.
- Aspecto: escenas animadas hechas de caracteres como fondo de la app (Translay, por defecto, con la onda del logo hablando; fondo marino, atardecer, medusas y arañas) con los colores del tema, un logo nuevo (una onda de voz y «translay») y JetBrains Mono para el código y los datos técnicos. Los bloques de código siguen el modo claro u oscuro: cada tema de código tiene su versión clara y oscura. Los íconos de los menús giran un poco al pasar el mouse, y el contenido principal tiene la esquina de arriba a la izquierda redondeada, donde se juntan el encabezado y la barra lateral. El encabezado y los paneles son levemente translúcidos, así la escena de fondo se asoma detrás. El texto seleccionado toma el color del tema.
- Fondos: un recorrido en escenas nuevas, cada una también un fondo por sí sola — **Luna** (los íconos de Translay en órbita alrededor de la Luna), **Tierra** (la Tierra que gira con sus continentes y nubes), **Nubes**, **Arrecife** (un arrecife de coral con una tortuga marina), **Ballena** (una ballena que cruza el mar abierto), **Abismo** (lo profundo, con un pez linterna y su señuelo que brilla) y **Naufragio** (un barco hundido en el fondo) — y **Recorrido**, que pasa por todas solo: del logo a la Luna, de bajada a la Tierra, el atardecer y el fondo del mar. En la bienvenida, los fondos se muestran en dos columnas.
- Agente: **Uso del equipo** (Ajustes › Agente) define cuánto del equipo toman el resumen y las descripciones: descansan entre pedidos, y en equipos sin tarjeta gráfica también limita los núcleos. Las preguntas siguen a toda velocidad.
- Reproductor: una descripción corta bajo el título del video (una o dos frases), escrita por el modelo más chico del agente al terminar de procesarlo, o tomada de su resumen.
- Agente: **Continuar** sigue una respuesta detenida desde donde quedó.
- Texto en el video: los títulos, letreros, diapositivas y comentarios del código escritos en un video se leen en la CPU (PP-OCRv5), se traducen y aparecen encima del original en el mismo lugar y con sus colores; el video traducido los lleva grabados en la imagen. El código, los comandos y los enlaces quedan como están, y los tipos de elementos nuevos se agregan con una función en `vt/textkind.py`. Activado por defecto (Ajustes › Audio y subtítulos › «Texto del video en español»), también en `GET /api/v1/videos/{id}/screen-text`.
- Transcripción: el código, los comandos, los enlaces y los comentarios del código escritos en el video aparecen en su lugar entre las frases, con un botón para copiarlos y un clic para ir ahí.
- «Copiar para un agente» (clic derecho en el video, una frase o una tarjeta) copia el video completo en Markdown para cualquier agente: transcripción con horas, personas y traducción, resumen, lo que aparece en pantalla y hasta dónde lo viste; también en `GET /api/v1/videos/{id}/context`.
- Agente: la pestaña «Resumen» pasa a ser el agente del video. Pregúntale lo que quieras (lo que se dice, lo que aparece en pantalla, en qué minuto pasa algo, qué te falta por ver) y responde en tu equipo, sin internet, con cada momento como un botón que lleva ahí y sugerencias según el video. Corre con llama.cpp en la tarjeta gráfica, la gráfica integrada o el procesador, con el modelo que entra en tu equipo; nombre, avatar, color, tono y modelo en Ajustes › Agente. El resumen es su primera tarjeta.
- Colores de código: el código, los comandos y los comentarios de la transcripción y del agente salen con el tema elegido en Ajustes › Apariencia (Visual Studio Code Dark por defecto; One Dark, Catppuccin, Dracula, Monokai, Nord y GitHub Light).
- Reproductor: un botón de subtítulos (CC) y la tecla <kbd>C</kbd> para elegir o apagar los subtítulos y el texto del video, también desde el clic derecho.
- Resumen: mucho más completo, escrito por el modelo del agente con lo que se dice y lo que aparece en pantalla: idea general, ideas para llevarse, capítulos con sus puntos y momentos, conceptos clave, y los enlaces, comandos y código del video como recursos. Se genera solo cuando el video está listo (Ajustes › Agente).
- Agente: su nombre, avatar, color y tono se cambian desde su propia pestaña (botón del pincel) sin salir del video; sus respuestas van en una burbuja con un tinte de su color, cada momento es un botón con ▶ de ese color y un video de ejemplo (resumen con capítulos, conceptos y recursos, y varias preguntas) queda junto a las opciones para mostrar cómo se verá, también en Ajustes.
- Reproductor: el código, los comandos, los enlaces y el texto traducido del video se copian o se le preguntan al agente desde el mismo video (al pasar el mouse, con clic o con clic derecho), con un recuadro que se desliza de uno a otro; el código y los comandos de la transcripción también tienen «Preguntar a Lumi».
- Agente: acciones con su propia tarjeta, al instante y también apagado: exportar el video para Claude u otro agente (copiar o descargar .md), ir a un momento o a donde se explica algo, cambiar los subtítulos, guardar el video en una colección y avisos mientras ves (marcados en la barra de avance, con un aviso al llegar a cada uno).
- Agente: con clic derecho en la barra de avance se pregunta sobre ese momento; aparece como una mención sobre la caja de preguntar.
- Agente: muestra cada paso mientras responde (cargar el modelo, leer el video, escribir), y cada mensaje muestra su hora y un botón para copiarlo; las respuestas terminadas llevan un check verde y las preguntas hechas mientras responde esperan en cola.
- Agente: antes de la primera pregunta muestra lo que sabe hacer con chips que preguntan o dejan la pregunta empezada.
- Agente: dicta las preguntas con el botón del micrófono; el Whisper de Translay escribe lo que dijiste en la caja para revisarlo antes de enviar.
- Ajustes › Agente: la lista de modelos indica cuáles son compatibles con tu equipo, cuál se recomienda, qué tan bien respondió cada uno en el laboratorio y cuáles ya están descargados; el elegido se puede descargar de antemano con el avance en el botón. Los modelos del agente aparecen en Ajustes › Almacenamiento, se borran de a uno y «Borrar los que tu perfil no usa» ya no los borra.
- Ajustes › Agente: un color «Del tema», marcado con su propio ícono, que sigue al color de énfasis de la app.
- Agente: se enciende o apaga desde su pestaña (apagado, el modelo deja la memoria; también entra en reposo tras 5 minutos sin preguntas). Las sugerencias de preguntas salen del resumen, así funcionan aunque esté apagado y al tocar una se enciende. Modelos por defecto elegidos con el laboratorio: Qwen3.5 4B o Gemma 4 E2B en tarjetas gráficas, Qwen3.5 0.8B en la gráfica integrada y Qwen3.5 2B o 0.8B en el procesador.
- Bienvenida de primer uso (en el navegador, con `run.py` o Docker): cuatro pasos para elegir el idioma (el de Windows por defecto), nombrar y dar estilo a la biblioteca, elegir modo, escena de fondo y color de énfasis (cambian detrás del diálogo al elegirlos) y armar la estrella del agente. Cada elección se guarda al momento; «Omitir» la cierra.
- App de escritorio: un asistente de primer uso en la ventana mientras se bajan el motor de voz y los modelos, con el avance de la descarga en su franja de abajo. Los pasos a la izquierda y, en cada uno, sus opciones junto a una vista previa en vivo: idioma (el asistente cambia al momento) y qué idioma solo se transcribe, cómo usarás Translay, la biblioteca principal (nombre, color, avatar y patrón, con su banner), apariencia (la ventana misma cambia), la estrella del agente, YouTube y el acceso desde el celular (los dos opcionales) y demostraciones cortas de la app con un cursor que hace clic. Translay abre con todo aplicado cuando el asistente termina y el servidor está listo.
- App de escritorio: la pantalla de arranque muestra la escena de fondo que elegiste (la primera vez, «Translay»), lo que se está cargando en palabras con su porcentaje y consejos sobre la app, en tu color de énfasis y tu idioma.

### Cambiado

- App de escritorio, asistente de primer uso › Apariencia: el modo se elige entre tres ventanitas (sistema, claro, oscuro) y el fondo con una miniatura de cada escena, en vez de filas con íconos; la demo de Exportar muestra el diálogo de exportar como es ahora (filas alineadas).
- Reproductor: reproducir como un ícono sin caja, el tiempo actual destacado sobre el total, una línea de avance sin bolita que se agranda al pasar el mouse, controles que solo se ven con el mouse sobre el video, la velocidad como un número que gira como una rueda y un selector de idioma que se abre dentro de la barra con el original y cada idioma de doblaje (uno en el que el video todavía no está lleva su marca y se prepara ahí mismo). Texto del video: Copiar y Preguntar van en una píldora que aparece donde está el mouse, Preguntar con la estrella del agente. La rueda del mouse funciona sobre la línea de avance (5 s), el volumen (5 %) y la velocidad.
- Los pedidos del agente, el resumen y la descripción van en inglés con la orden de responder en el idioma de la app, repetida al final de cada pedido: las respuestas en el idioma pedido pasaron de 0–93 % a 93–100 % en los cuatro modelos por defecto y los tres idiomas.
- Traductor de respaldo: MADLAD-400 3B (Apache-2.0) en vez de NLLB-200 (CC-BY-NC); empata o gana a NLLB en los pares medidos.
- Las tarjetas de video se abren con un clic en cualquier parte (sin botón «Ver»/«Continuar» ni botón de reproducir sobre la miniatura); «⋯» abre el menú del clic derecho y reemplaza la «X» suelta para quitar de una colección.
- El título, la descripción y los botones del video van debajo del video. Los diálogos se cierran al hacer clic afuera.
- Tema oscuro: sin bordes ni grises más claros que el de lo activo; lo elegido con el color de énfasis; lo siguen los diálogos, los campos, las pestañas, el panel de transcripción, los bloques de código y todas las páginas de Ajustes. Los avatares de biblioteca son sólidos; el diálogo de crear o editar biblioteca muestra su escena con «Otro patrón» y «Al azar». Ajustes › Acceso muestra una fila por biblioteca con su acceso en un desplegable.
- La luz de banner detrás de los encabezados de colecciones y canales es más tenue.
- El color de énfasis se recuerda en el navegador y se aplica antes de pintar la página (sin botones ni logo en blanco al cargar).
- Ajustes: la sesión de YouTube pasó a Agregar y descargar, y Uso ahora dice para qué sirve.
- Color de énfasis: pasteles suaves en claro con el texto en un tono profundo del mismo color (sin texto negro sobre el verde); cada muestra en Ajustes enseña su versión en claro y en oscuro, partidas por una diagonal ondulada.
- Fondo (antes «Fondo del inicio»): las luces de la miniatura y del color y la galería se reemplazan por las escenas; la imagen propia sigue.
- Textos de la interfaz revisados en toda la app para que suenen a producto terminado: «Descargar» en vez de «Bajar», «Iniciar sesión» y «propietario», «Priorizar», «Notificaciones», «Estilo de respuesta», «Dispositivo», «Ideas clave», «Subtítulos activados» y avisos cortos sin dos puntos ni punto final.
- La opción elegida en pestañas, grupos de opciones, ES / EN y botones activos se marca solo con su tono, sin anillo ni sombra.
- Inicio: lo que estás viendo va primero, grande, con la luz de su miniatura detrás; la caja para agregar salió del inicio (agregar y grabar están en la barra de arriba). El fondo se elige en Ajustes › Apariencia › «Fondo del inicio»: la luz del video, la del color de énfasis, liso o una imagen propia, con el inicio de verdad como vista previa. Ocho fondos más en una galería (Aurora, Atardecer, Océano, Bosque, Brasa, Medianoche, Arena, Niebla), y el texto del destacado pasa a claro u oscuro para leerse sobre cualquier fondo. En pantallas grandes el destacado crece con la ventana y muestra las ideas clave y los primeros capítulos de su resumen, cada uno un botón a ese momento.
- La barra lateral y el panel del video cambian de ancho arrastrando su borde; pasado el mínimo, la barra queda en íconos y el panel se oculta (se vuelve a sacar arrastrando su borde). Se quitó el botón «Transcripción» sobre el video: el panel tiene más que la transcripción.
- Encabezado: los botones son siempre los mismos y en el mismo lugar (Grabar, Agregar, Cola, Biblioteca, Ajustes), con el de la pantalla abierta marcado; «Biblioteca» ya no se convierte en «Volver al video». Un video abierto queda en la miniatura de abajo a la derecha también en pausa, para volver a él.
- Biblioteca: al pasar el mouse sobre un video descargado se reproduce una vista previa sin sonido en su miniatura, como en YouTube.
- Colecciones, playlists, canales y categorías abren con un encabezado (distintivo, nombre, videos y acciones) con la luz de su banner o sus miniaturas detrás, como el modo ambiente de YouTube. El patrón de puntos salió de los banners, las tarjetas y las bibliotecas.
- Tema oscuro: grises neutros puros, sin el tinte azulado (fondo #161616, paneles #181818, campos #1f1f1f, menús #1a1a1a).
- App de escritorio: ícono nuevo (la onda de voz en violeta sobre un cuadro oscuro) en la ventana, la barra de tareas, el menú Inicio y el instalador, y el logo nuevo en las pantallas de preparación y de arranque.
- App de escritorio: las pantallas de preparación y de arranque y el instalador, en español, inglés y portugués.
- Sitio web: una portada nueva con el diseño de la app (oscuro neutro, sin bordes, énfasis violeta) y sus escenas de caracteres en vivo: el fondo de toda la página es un viaje por esas escenas a medida que se baja: los íconos de Translay orbitan la Luna, se baja a la Tierra, entre las nubes hasta el atardecer, y se bucea por el arrecife, una ballena, las medusas y el abismo hasta un barco hundido en el pie, demostraciones vivas de cada función (un reproductor con transcripción, personas y cómo encaja cada frase, el texto del video traducido con Copiar y Preguntar a Lumi, una conversación con Lumi y el creador de su estrella, bibliotecas con su patrón y la búsqueda, agregar, la cola y exportar, y el proceso), un recorrido por capturas actuales, un probador donde la escena, el color de énfasis y el modo cambian la página entera, y los idiomas al día. La documentación usa el logo, los colores y JetBrains Mono nuevos.
- Documentación: capturas nuevas con el diseño nuevo, y otras del agente y el texto en el video; «Tu primer video» explica cómo se elige el idioma (Ajustes › Uso › Idioma y «Traducir a»), y la guía de la Biblioteca, que los diálogos se cierran con un clic afuera.
- Exportar: una fila alineada por tipo (Video, Audio, Subtítulos y Texto) con su formato junto al nombre, sus opciones y la calidad o el formato a la derecha, y opciones con nombres más cortos; la tarjeta elegida toma apenas un toque del color de énfasis y la calidad o la carpeta elegidas, el tono de selección del énfasis.
- Documentación: las capturas siguen el tema claro u oscuro de la página, tomadas de nuevo con el violeta de fábrica; los enlaces de página anterior y siguiente son más chicos y sin borde. El README usa el logo nuevo.

### Corregido

- App de escritorio: cuando la descarga ya terminó y se están desempacando los paquetes, la instalación dice «Terminando de instalar» con una barra de espera en vez de quedarse quieta en 97 %.
- Bibliotecas: «Nueva biblioteca» y «Editar» se abren encima de la pantalla de Bibliotecas en vez de cerrarla antes (sin parpadeo), y «Cancelar» vuelve a ella.
- La esquina redondeada donde se juntan el encabezado y la barra lateral acompaña a la barra mientras se abre o se cierra, en vez de adelantarse.
- Encabezado en el celular: el botón de la biblioteca ya no queda debajo del de agregar, y en pantallas muy angostas (320 px) todos los botones quedan en la primera fila.
- Biblioteca de demostración: las tarjetas ya no muestran «Doblado 2 %» (el tiempo cubierto se estira junto con las frases) y cada video demo tiene su propio audio doblado.
- El reproductor ya no pide una y otra vez un audio doblado que falta (miles de pedidos): un archivo que no existe no se vuelve a pedir y un error de red se reintenta a los pocos segundos.
- El chat del agente ya no vibra al hacer scroll mientras escribe: solo se actualiza la respuesta en curso.
- Aspecto: las escenas de fondo usan como máximo el 15 % de un núcleo del procesador en cualquier equipo (celdas más grandes en pantallas grandes, un tope de uso y las posiciones calculadas una vez por cuadro), y se detienen mientras se reproduce un video y cuando usas otra ventana (las dos cosas se pueden desactivar en Ajustes › Apariencia).
- Aspecto: la escena de fondo se dibuja en su propio hilo, con caracteres ya dibujados y solo donde algo cambió, así la navegación ya no se pone lenta (en pantalla completa llegaba a tomar la mitad del tiempo de la interfaz).
- Ajustes: la píldora de la opción elegida ahora se desliza a la nueva en todos los grupos de opciones (al redibujar la página, saltaba).
- Agente: detener una respuesta funciona al instante, también mientras todavía lee el video, y deja lo que alcanzó a escribir.
- Script de versiones: ya no falla en la consola de Windows al mostrar las notas; escribe su salida en UTF-8.
- Ajustes › Agente: la muestra del color «El de énfasis» no se veía.
- Agente: si Translay se cierra de golpe, el servidor del modelo se cierra con él en vez de quedarse en la memoria.

## 1.13.0 · 2026-11-13

### Agregado

- Transcripción y «Personas»: cada persona de un video tiene su color apagado (azul, violeta, verde azulado, dorado, rosa), en su nombre en la transcripción y en su P1, P2…, para seguir de un vistazo quién habla.
- Inicio: la caja para agregar entra con una animación suave al llegar, y su título cambia con una animación corta al elegir «Traducir y doblar» o «Solo transcribir».
- Sitio de documentación: una portada nueva que presenta Translay, con una muestra del reproductor y su transcripción alineada que se puede usar, los cinco pasos del doblaje, todas las funciones, capturas reales, el perfil que elige para cada GPU, acceso y API, instalación, lo nuevo de la última versión y preguntas frecuentes, en inglés y español y en claro y oscuro.

### Cambiado

- Grupos de opciones (Traducir y doblar / Solo transcribir, claro u oscuro, formatos de exportación…): la opción elegida es una píldora que se desliza suave a la nueva; también las pestañas del panel del reproductor (Transcripción, Resumen, Personas) y el cambio ES / EN.
- Los diálogos aparecen suave y los avisos suben al aparecer y se desvanecen al irse, en vez de saltar.
- Tema oscuro: diálogos, menús, campos y la opción elegida usan los grises nuevos, más oscuros y apenas sobre las barras, en vez del gris claro de antes; los campos de texto y las listas desplegables ya no tienen relleno gris, solo una línea fina.
- Colecciones, canales y categorías sin banner propio siempre tienen color: se quitó el campo de puntos gris.
- Documentación y README: todas las capturas se volvieron a tomar con la versión actual, en oscuro y en claro.

### Corregido

- Biblioteca: con videos elegidos, el título, cuántos y las acciones quedan en una fila; si las acciones no caben, muestran solo su ícono en vez de encimarse o salirse.
- Reproductor: «Listo para reproducir» ya no tapa el subtítulo en inglés arriba de la vista ampliada, y en la vista dividida la transcripción muestra el original pequeño arriba del español en vez de dos columnas muy angostas.

## 1.12.0 · 2026-11-12

### Agregado

- Cola: «Detener» y «Continuar» en cada trabajo detienen la descarga y el procesamiento de un solo video sin perder su lugar; «Detener todo» ahora también frena las descargas, no solo el procesamiento (el video que ves sigue).
- Transcripción: los tramos aún sin transcribir aparecen entre las frases como «Aún sin transcribir», o «Transcribiendo esta parte» mientras se procesan, así adelantar el video no parece un error; un clic lleva ahí.
- App de escritorio: en Windows 11, dejar el mouse sobre maximizar o mantenerlo presionado abre los diseños de ajuste.
- Grabar pantalla: si la fuente cambia de forma a mitad (de un celular a la pantalla del escritorio), el video final entra completo en un solo cuadro sin deformarse; antes todo quedaba apretado en la forma de la primera fuente.
- Ajustes › Uso: **Transcribir y resumir**, un modo para grabar o agregar videos y usar su transcripción y sus resúmenes; no aparece nada de traducción ni de voz y el servidor no carga el traductor ni la voz. Lo traducido se conserva, y lo que agregues en este modo queda como solo transcribir.
- Inicio: la caja para agregar («Traduce un video») queda arriba del inicio aunque haya videos, con el campo del enlace, «Subir archivos», «Grabar pantalla» y «Varios enlaces»; se quitó el video destacado grande de abajo (lo que estás viendo queda en su fila «Seguir viendo»). Al arrastrar archivos sobre la ventana aparece «Suelta para agregar».

### Cambiado

- Cola: «Priorizar» salió de la biblioteca (se leía como ordenar la biblioteca) y en la Cola es «Hacer primero»; los trabajos ya no muestran «en pausa» ni un botón de reproducir (se leían como reanudar la cola): el título abre el video y el clic derecho tiene «Abrir el video».
- Ajustes › App de escritorio: «Seguir en la bandeja» dice que Translay se cierra igual si la cola está detenida o no hay nada en proceso.
- Encabezado: «Grabar» y «Agregar» como dos botones separados; ya no hay botones divididos (Agregar ▾, Ver ▾, Conectar ▾) ni el botón que cambiaba de acción con el uso (se quitó su preferencia «Botón Agregar»). El panel Agregar elige «Traducir y doblar» o «Solo transcribir» y cada fuente dice qué acepta.
- «Preferencias» ahora es «Ajustes», con ícono de engranaje.
- El logo del encabezado va primero, a la izquierda, con sus colores (coral con la marca blanca) en vez del color de énfasis del tema; el botón de la barra lateral pasa a su derecha.
- Tema oscuro: barras y tarjetas más oscuras, apenas más claras que el fondo de la página. Tema claro: la página es casi el blanco de las barras, un poco más apagado, en vez de gris.
- El encabezado ya no muestra «En reposo» ni el trabajo de la cola: lo dice el panel de la Cola, y en el encabezado solo aparece un estado sin conexión o con algo puntual (buscar un video).
- Patrones de colecciones y bibliotecas: un color sólido con un campo de puntos parejo en vez de las figuras Bauhaus (círculos, triángulos y cuadrados).

### Corregido

- Un video en español (una clase de Zoom grabada en vivo) se reconocía como inglés: con ruido o una sala de espera Whisper decía «inglés» con poca confianza y traducía todo al inglés y de vuelta. La detección en vivo ya no decide por debajo de 50 %, la cola detecta con tres puntos del archivo y confirma con el archivo completo un idioma decidido en vivo, y lo rehace si era otro.
- Un video que no se traduce (ya en español) se reproduce siempre en vez de quedarse en «Preparando» (esperaba una traducción que nunca llega), y cuando el original y la traducción de un subtítulo dicen lo mismo, se muestra uno solo.
- Grabar pantalla: «Sin conexión» ya no queda para siempre cuando solo la transcripción en vivo no se conectó; una fuente que deja de enviar imagen lo avisa, una que desaparece termina y guarda la grabación, y una grabación que el servidor rechaza dice por qué en vez de reintentar sin fin.

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
