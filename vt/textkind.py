"""¿Qué es cada renglón de texto que aparece en un video? Un registro de tipos, extensible.

  KINDS                 nombre → Kind (etiqueta, si se traduce, si forma bloques de código)
  register(...)         agrega un tipo: `@register("email", "Correo", order=25)` sobre su función
  kind(text)            el tipo de un renglón ("text" si ninguno lo reconoce)
  settle(kinds)         corrige un bloque: en uno de código, lo dudoso también es código
  translatable(name)    ¿se traduce? (el texto común y los comentarios sí; el código, no)

En un curso de programación, traducir `return data` o `pip install requests` arruina lo que se
ve: el código, los comandos y los enlaces se dejan como están y los comentarios se traducen.

Cada tipo es una función `texto → bool | float`: los que devuelven bool deciden solos, en orden
(`order` menor primero); los que devuelven un puntaje compiten y gana el más alto si llega a su
`threshold`. Para que Translay reconozca un elemento nuevo basta registrar su función aquí; el
resto (seguimiento, guardado, la vista) usa el nombre y la etiqueta del registro.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

DEFAULT = "text"


@dataclass(frozen=True)
class Kind:
    name: str
    label: str                       # cómo se llama en la vista
    test: Callable[[str], object]    # bool (decide) o float (puntaje)
    order: int = 50                  # en qué orden se prueba
    translate: bool = False          # se traduce y se pone encima del original
    block: bool = False              # domina su bloque: lo dudoso a su alrededor pasa a ser de este tipo
    threshold: float = 1.0           # puntaje mínimo (solo los de puntaje)
    joiner: str = " "                # cómo se unen sus renglones en un bloque
    where: bool = False              # la función recibe también dónde está: test(texto, ctx), ctx = {h, y}


KINDS: dict[str, Kind] = {}


def register(name: str, label: str, **opts):
    """Decorador: registra la función como el reconocedor del tipo `name`."""
    def wrap(fn):
        KINDS[name] = Kind(name, label, fn, **opts)
        return fn
    return wrap


def translatable(name: str) -> bool:
    k = KINDS.get(name)
    return bool(k and k.translate)


def joiner(name: str) -> str:
    k = KINDS.get(name)
    return k.joiner if k else " "


_LETTERS = re.compile(r"[^\W\d_]")


def _letters(s: str) -> int:
    return len(_LETTERS.findall(s))


# lo que el editor o la consola ponen delante del código: número de línea, celda de Jupyter, prompt de Python
_GUTTER = re.compile(r"^(?:\d{1,4}\s+(?=\S)|\[\d*\]:?\s*|In \[\d*\]:\s*)")
_REPL = re.compile(r"^(?:>>>|\.\.\.)\s")


def gutter(text: str) -> str:
    """El renglón sin el número de línea del editor ni la marca de celda: `22 activity = [` → `activity = [`."""
    t = text.strip()
    m = _GUTTER.match(t)
    return t[m.end():] if m and m.end() < len(t) else t


def kind(text: str, ctx: dict | None = None) -> str:
    """ctx: dónde está el renglón, en fracción del cuadro: {"h": alto, "y": arriba}. Sin ctx, los tipos
    que dependen del lugar (la interfaz) no se prueban."""
    t = text.strip()
    if _REPL.match(t):
        return "code"  # >>> import this
    t = gutter(t)
    scores: list[tuple[float, int, str]] = []
    for k in sorted(KINDS.values(), key=lambda k: k.order):
        if k.where:
            if ctx is None:
                continue
            r = k.test(t, ctx)
        else:
            r = k.test(t)
        if isinstance(r, bool):
            if r:
                return k.name
        elif r is not None and r >= k.threshold:
            scores.append((float(r), -k.order, k.name))
    return max(scores)[2] if scores else DEFAULT


def settle(kinds: list[str]) -> list[str]:
    """En un bloque donde la mayoría es de un tipo que domina (código, comandos), lo que quedó
    como texto común también lo es: `data`, `else`, `end` sueltos no son frases."""
    hard = [k for k in kinds if k in KINDS and KINDS[k].block]
    if len(hard) >= 2 and len(hard) * 2 >= sum(k != "noise" for k in kinds):
        main = max(set(hard), key=hard.count)
        return [main if k == DEFAULT else k for k in kinds]
    return kinds


# ------------------------------------------------------------------- tipos
KINDS[DEFAULT] = Kind(DEFAULT, "Texto", lambda t: None, order=999, translate=True)  # lo que nadie reconoce


@register("noise", "Ruido", order=0)
def _noise(t: str) -> bool:
    """Íconos y restos: menos de dos letras."""
    return _letters(t) < 2


# sin `'` (VB) ni `* ` (JSDoc): en los videos casi siempre eran un string cortado o un archivo modificado
_COMMENT = re.compile(r"^(?://|#(?![\w-]*[({=<])(?!include\b|define\b|pragma\b|region\b)|/\*|\*/|<!--|--\s"
                      r"|rem\s)", re.I)


# alto del renglón (fracción del cuadro, con el margen de la caja). Medido en tools/lab/screentext.py: la
# barra lateral y las pestañas de un navegador compartido miden 0,020–0,030; los títulos reales, desde 0,030.
UI_H = 0.0295     # bajo esto, letra de interfaz (~21 px en 720p)
UI_UNSURE_H = 0.036
UI_UNSURE_CONF = 0.95  # en el borde, lo que el OCR lee con poca seguridad es interfaz mal leída (0,77–0,94);
                       # el contenido de ese tamaño se lee con 0,97–1,00
UI_SCREEN = 5  # textos chicos en el mismo cuadro desde los que es una pantalla (navegador, editor, app)
UI_GARBLED_CONF = 0.85  # en una pantalla, por debajo de esto la lectura sale mezclada (medido en la cinta de Office)
_FUNCTION_WORDS = {"the", "a", "an", "to", "of", "and", "in", "for", "is", "it", "you", "with", "on", "that", "this",
                   "can", "are", "be", "your", "how", "what", "i", "if", "do", "my", "we", "our", "from", "by", "or",
                   "as", "at", "was", "will", "me", "when", "there", "they", "about"}


def _prose(toks: list[str]) -> bool:
    """¿Una frase? Cinco palabras o más con al menos dos palabras de enlace (the, to, you…)."""
    words = [w.strip(".,;:!?()\"'").lower() for w in toks]
    fw = sum(w in _FUNCTION_WORDS for w in words)
    return (len(words) >= 5 and fw >= 2) or (len(words) >= 6 and fw >= 1)
_SHORTCUT = re.compile(r"^(?:\^[A-Za-z\\\]_]|M-[A-Za-z])")
_KEY = re.compile(r"^(?:ESC|TAB|CAPS|SHIFT|CTRL|ALT|FN|ENTER|RETURN|BACK|DEL|INS|HOME|END|PGUP|PGDN|SPACE|WIN|CMD|OPT|"
                  r"F\d{1,2})+$", re.I)  # teclas enteras, también pegadas (CTRLALT); `Optious` no es Option
_MENU = {"File", "Edit", "View", "Selection", "Find", "Go", "Goto", "Run", "Terminal", "Help", "Window", "Tools",
         "Insert", "Format", "Cell", "Kernel", "Widgets", "Project", "History", "Bookmarks", "Profiles", "Shell",
         "Develop", "Navigate", "Refactor", "Build", "Debug", "Tabs", "Extensions", "Preferences", "Toolbelt",
         # la barra lateral de los archivos (Finder, Explorador) y los menús de Jupyter
         "Favorites", "Applications", "Desktop", "Documents", "Downloads", "Recent", "Devices", "Users", "Pictures",
         "Music", "Videos", "Markdown", "NBConvert",
         # la cinta de Office (PowerPoint, Excel, Word), también en MAYÚSCULAS
         "Home", "Draw", "Design", "Layout", "Formulas", "Data", "Review", "Automate", "Developer", "Transitions",
         "Animations", "Slide", "Show", "Add-ins", "References", "Mailings", "Pivot", "Copilot"}
_KEY_ROW = re.compile(r"^(?:ESC|TAB|CAPS|SHIFT|CTRL|ALT|ENTER)[A-Z]{3,}$")


@register("ui", "Interfaz", order=3, where=True)
def _ui(t: str, ctx: dict) -> bool:
    """Letra chica y corta: pestañas, marcadores, menús y barras de una pantalla compartida. Tapada sería
    ilegible, y el OCR la lee mal a ese tamaño. Un comentario o una frase chica sí se traducen."""
    if _COMMENT.match(t):
        return False
    toks = t.split()
    if toks and sum(bool(_SHORTCUT.match(w)) for w in toks) >= max(1, len(toks) // 4) and len(toks) <= 10:
        return True  # barra de atajos de un editor de terminal: ^X Exit, M-U Undo
    keys = sum(bool(_KEY.match(w)) or (w.isupper() and bool(_KEY_ROW.match(w))) for w in toks)  # CTRL, CAPSASDF
    single = sum(len(w) == 1 and not w.isdigit() for w in toks)  # Q W E R T Y, S M L
    keyish = sum(bool(_KEY.match(w)) or (len(w) <= 2 and not w.isdigit() and not (w.isalpha() and w.islower()))
                 or (w.isupper() and bool(_KEY_ROW.match(w))) for w in toks)
    # un teclado dibujado (ESC, TAB Q W E R T Y, CTRL ALT, F1 F2): teclas de verdad o una fila de letras
    # sueltas; `3. Why It Wo` (un título que aparece) no
    if toks and keyish / len(toks) >= 0.75 and (keys or single >= 3):
        return True
    menu = sum(w in _MENU or w.title() in _MENU for w in toks)
    if (menu >= 3 or (menu >= 2 and len(toks) <= 4)) and not re.search(r"[.!?,]", t):
        return True  # la barra de menú de una app: File Edit View … Help
    if ctx.get("small", UI_SCREEN) < UI_SCREEN:
        return False  # pocos textos chicos en el cuadro: es una animación o una diapositiva, no una pantalla
    h = ctx.get("h", 1)
    if ctx.get("conf", 1) < UI_GARBLED_CONF:
        return True  # en una pantalla, una lectura dudosa nunca se tapa con una traducción («Bring FowardAlig3.79 m»)
    if h < UI_UNSURE_H and ctx.get("conf", 1) < UI_UNSURE_CONF:
        return True  # chica y mal leída en una pantalla: pestañas y listas que el detector juntó en una tira
    if _prose(toks):
        return False  # una frase bien leída (un foro, un artículo en la pantalla): se lee, no es un botón
    words = [w for w in toks if _letters(w)]
    sentence = len(words) >= 3 and re.search(r"[.!?]$", t)
    return h < UI_H and len(words) <= 6 and not sentence


@register("comment", "Comentario", order=10, translate=True)
def _comment(t: str) -> bool:
    """// …, # …, /* … */, <!-- … -->, -- … (SQL), ; … , REM …"""
    return bool(_COMMENT.match(t))


_MARK = re.compile(r"^(\s*(?://+|#+|/\*+|\*+|<!--|--|;+|rem\b|')\s*)(.*?)(\s*(?:\*/|-->)\s*)?$", re.I | re.S)


def comment_parts(text: str) -> tuple[str, str, str]:
    """`# read the config` → ("# ", "read the config", ""): la marca se conserva y solo se traduce el texto."""
    m = _MARK.match(text)
    return (m.group(1), m.group(2), m.group(3) or "") if m else ("", text, "")


@register("hashtag", "Hashtag", order=9)
def _hashtag(t: str) -> bool:
    """#rtgfx4all: una etiqueta de redes, una sola palabra pegada al #, se deja como está (un comentario
    de código lleva espacio después del #)."""
    return bool(re.fullmatch(r"#[A-Za-z][\w]{2,}", t))


@register("handle", "Usuario", order=14)
def _handle(t: str) -> bool:
    """@monarchwebworld: una cuenta de redes sociales se deja como está."""
    return bool(re.fullmatch(r"@[\w.]{3,}", t))


@register("email", "Correo", order=15)
def _email(t: str) -> bool:
    return bool(re.fullmatch(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", t))


_URL = re.compile(r"^(?:https?:/+|www\.)\S+$|^[\w-]+(?:\.[\w-]+)*\.(?:com|org|net|io|dev|app|ai|co|edu|gov|"
                  r"me|tv|ly|gg|xyz|info|es|mx|ar|br|uk|de)(?:/\S*)?$", re.I)


@register("link", "Enlace", order=20)
def _link(t: str) -> bool:
    return bool(_URL.match(t))


_PROMPT = re.compile(r"^(?:\$|>|%|#)\s+\S|^(?:PS\s+)?[A-Za-z]:\\[^>]*>\s*\S|^[\w.-]+@[\w.-]+[:~][^$#]*[$#]\s")
CLI = {
    "pip", "pip3", "pipx", "uv", "uvx", "python", "python3", "py", "conda", "poetry", "npm", "npx", "pnpm", "yarn",
    "bun", "deno", "node", "git", "gh", "cd", "ls", "dir", "mkdir", "rm", "rmdir", "cp", "mv", "cat", "echo",
    "touch", "chmod", "chown", "sudo", "apt", "apt-get", "brew", "winget", "choco", "docker", "kubectl", "helm",
    "dotnet", "cargo", "rustup", "go", "java", "javac", "mvn", "gradle", "curl", "wget", "ssh", "scp", "export",
    "source", "make", "cmake", "gcc", "g++", "clang", "composer", "php", "artisan", "rails", "bundle",
    "gem", "flutter", "dart", "terraform", "az", "aws", "gcloud", "code", "nano", "vim", "grep",
    "tar", "unzip", "systemctl", "ollama", "ng", "vite", "tsc", "jest", "pytest", "ffmpeg", "yt-dlp",
}


@register("command", "Comando", order=30, block=True, joiner="\n")
def _command(t: str) -> bool:
    """Con prompt ($, >, PS C:\\…>) o empieza con un programa de consola conocido y tiene sus argumentos."""
    m = _PROMPT.match(t)
    if m:
        rest = t[1:].split() if t[0] in ">%#" else None
        # `> OUTLINE` (un árbol del editor) no es un prompt: después de > va un programa conocido
        return rest is None or (bool(rest) and rest[0] in CLI)
    m = re.match(r"^[\w.~/-]+\s?>\s+(\S+)", t)
    if m and m.group(1) in CLI:
        return True  # el prompt de una carpeta: docker-demo > docker run myapp
    words = t.split()
    # el programa en minúscula, como se escribe (`Python version:` es un título) y un argumento con forma
    # de argumento (`cat = [...]` es código; `python +`, nada)
    return words[0] in CLI and len(words) > 1 and bool(_ARG.match(words[1])) and words[1] not in _PROSE \
        and not re.search(r"[.!?:]$", t) \
        and bool(re.search(r"(^|\s)--?\w|[\\/.@=]", t) or len(words) <= 4)


# `python is now available…`: después del programa va una palabra de una frase, no un argumento
_PROSE = {"is", "are", "was", "were", "will", "can", "has", "have", "the", "a", "an", "and", "or", "to", "for", "in",
          "on", "of", "with", "that", "this", "it", "also", "now", "lets", "let's"}
_ARG = re.compile(r"^(?:--?\w|[a-z0-9./~\"'$*][\w./\\:@=~\"'*,-]*$)")


KEYWORDS = {
    "def", "class", "function", "func", "fn", "const", "let", "var", "return", "import", "from", "export",
    "async", "await", "public", "private", "protected", "static", "void", "int", "string", "bool", "float",
    "double", "char", "using", "namespace", "package", "struct", "enum", "interface", "impl", "elif", "else",
    "switch", "case", "try", "catch", "except", "finally", "throw", "raise", "new", "lambda", "yield", "pub",
    "mut", "val", "type", "extends", "implements", "include", "require", "module", "select", "insert",
    "update", "delete", "create", "where", "print", "console", "self", "this", "null", "none", "true",
    "false", "nil", "foreach", "while", "for", "if", "end", "begin", "then", "do", "unless", "#include",
    "#define",
}
# palabras clave que también son palabras comunes en inglés: suman poco sin símbolos de código
_SOFT = {"for", "if", "do", "end", "then", "while", "type", "new", "case", "select", "update", "delete",
         "create", "where", "print", "from", "import", "return", "set", "begin", "include", "module",
         "require", "true", "false", "none", "this", "self", "try", "else", "export"}
_CALL = re.compile(r"[A-Za-z_]\w*\(")  # `print(`: una llamada no lleva espacio (`Outputs (code)` es texto)
_ACCESS = re.compile(r"\b[A-Za-z_]\w+(?:\.[A-Za-z_]\w+)+\b")  # os.path, app.run; no siglas (U.S., V.C)
_CAMEL = re.compile(r"\b\w*[a-z][A-Z]\w*\b")  # camelCase, PascalCase, EFMigrations
_SNAKE = re.compile(r"\b[a-z]+_[a-z_\d]+\b")
_OPS = re.compile(r"=>|->|==|!=|<=|>=|:=|\+=|-=|&&|\|\||::|</?\w+[^>]*>|[{};]\s*$|^\s*[{}\])]")
_ASSIGN = re.compile(r"^\s*[\w.\[\]\"']+\s*[:=]\s*\S")
_IMPORT = re.compile(r"^(?:import\s+[\w{*][^.!?]*\s+from\s+\S|from\s+[\w.]+\s+import\s|import\s+[\w.]+(?:\s+as\s+\w+)?$"
                     r"|using\s+[\w.]+;)")
# datos: volcados hexadecimales, versiones, horas, números sueltos (`00 64 09 cd`, `3.7.3`, `22:22:05`)
_DATUM = re.compile(r"^[(\[]?(?:[0-9a-fA-F]{2}|v?\d+(?:[.:,]\d+)*[.,%)\]]?|0x[0-9a-fA-F]+)[,)\]]?$")
# Python y afines: `if True:`, `class Reptile:`, `else:`, `def f(x):`
_BLOCK_KW = re.compile(r"^(?:if|elif|else|for|while|def|class|try|except|finally|with|match|case|async def)\b[^.!?]*:")
_MULTI_ASSIGN = re.compile(r"^\s*\w+(?:\s*,\s*\w+)+\s*=\s*\S")
_ARITH = re.compile(r"\b\w+\s[*%]\s\w+|\)\s*:")  # sin `/`: en prosa es «o» (`Tool calls / MCP calls`)
_FILE = re.compile(r"\b[\w-]{2,}\.(?:py|ipynb|js|mjs|ts|tsx|jsx|json|md|html|css|scss|ya?ml|toml|rs|go|java|kt|cs|cpp|"
                   r"c|h|rb|php|sh|ps1|bat|txt|csv|db|sql|xml|lock|env|cfg|ini|dockerfile)\b"
                   r"|\b(?-i:[a-z][\w-]*\.[a-z]{2,10})\b", re.I)  # cualquier extensión, solo en minúsculas
# archivos sin extensión, con su grafía exacta (`DOCKERFILE` en un título es texto)
_BARE_FILE = re.compile(r"\b(?:Dockerfile|Makefile|README\.?|LICENSE|Gemfile|Procfile|Jenkinsfile)\b")
_NUMBERED = re.compile(r"^[A-Za-z][a-z]*\d+$")  # linode2, file10: listados de archivos
_VIM = re.compile(r"^:(?:wq?|q|x|w!|q!|wq!|set\b.*|\d+)$")
_PATH = re.compile(r"(?:^|[\s:(])~?/?[\w.-]+/[\w.-]+")
# más lenguajes que aparecen en cursos: regex, SQL, HTML, CSS, YAML y una asignación cortada
_REGEX = re.compile(r"^/[^/\s]+/[gimsuy]*$")
_SQL = re.compile(r"^(?:select\s+(?:\*|[\w.,\s]+?)\s+from|insert\s+into|update\s+\w+\s+set|delete\s+from|create\s+table"
                  r"|alter\s+table|drop\s+table)\b", re.I)
_HTML = re.compile(r"\b[\w-]+=\"|^</?[a-z][\w-]*\b(?![.!?])|^/[a-z]+\d?$")
_CSS = re.compile(r"^[.#][a-zA-Z][\w-]*\s*\{?$|^[a-z]+(?:-[a-z]+)+\s*:")
_YAML_KEY = re.compile(r"^[a-z_][\w-]*:$")
_DECL = re.compile(r"^(?:const|let|var|def|function|fn|func|struct|enum|interface|class)\s+[A-Za-z_]\w*")
_HALF_ASSIGN = re.compile(r"^[A-Za-z_][\w.]*\s*=$")
# fórmulas de hoja de cálculo: =VLOOKUP(D2,A2:B16,2,FALSE), = FALSE, A2:B16
_FORMULA = re.compile(r"(?:^|\s)=\s*[A-Za-z]+\d*\s*\(|^[=↑]\s*(?:TRUE|FALSE|\d|\"|\{)|\b[A-Z]{1,2}\d+:[A-Z]{1,2}\d+\b")


def shell(text: str) -> bool:
    """¿Es un renglón de terminal (prompt o salida típica)? Para dar contexto al resto del cuadro."""
    t = gutter(text)
    return bool(_SHELL.search(t) or _PROMPT.match(t))
# la terminal: un prompt en cualquier parte (`exit chuck@host:~$`), permisos de `ls -l`, «programa: error»,
# ids hexadecimales (`1e4467b07108`), `[sudo]`, el prompt de una carpeta (`docker-demo > docker run`)
_SHELL = re.compile(r"\w+@[\w.-]+:[~/][^\s]*[$#]|^[\w.-]+:[\w~/.-]+ [\w.-]+\$|(?:^|\s)[-dlcb][rwx-]{8,9}(?:\s|$)|^\[sudo\]"
                    r"|^[a-z][\w-]*: (?:[a-z]|Permission|No such|cannot|failed)|^[a-z][\w.~/-]*\s?>$")
_HEXID = re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{10,}\b")
# Dockerfile: la instrucción en mayúsculas y un argumento con forma de código (`RUN some commands` es texto)
_DOCKER = re.compile(r"^(?:FR[O0]M|RUN|ENV|CMD|COPY|ADD|WORKDIR|EXPOSE|ENTRYPOINT|ARG|USER|VOLUME|LABEL)\s+\S*[:=/.\-\[\"]")


@register("code", "Código", order=40, block=True, threshold=2.0, joiner="\n")
def _code(t: str) -> float:
    """Puntaje: símbolos, operadores, llamadas, nombres con forma de código y palabras clave."""
    words = t.split()
    if re.fullmatch(r"(?:[A-Za-z]\.){2,}[A-Za-z]?\.?", t):
        return 0.0  # una sigla: U.S.A.
    first = words[0].lower().rstrip(":({")
    score = 0.0
    # las comillas cuentan de a pares (un string): una suelta es un texto animado que se corta («"Dig»)
    quotes = sum(t.count(q) // 2 * 2 for q in "\"'")
    sym = (sum(t.count(c) for c in "(){}[];=<>_`$&|\\") + quotes) / max(1, len(t))
    score += min(2.0, sym * 12)
    if _OPS.search(t):
        score += 1.5
    if _CALL.search(t):
        score += 1.0
    if _ACCESS.search(t):
        score += 1.0
    if _CAMEL.search(t) or _SNAKE.search(t):
        score += 1.0
    if _ASSIGN.match(t):
        score += 1.0
    if _IMPORT.match(t):
        score += 1.5
    data = sum(bool(_DATUM.match(w)) for w in words) / len(words)
    if (len(words) >= 4 and data >= 0.5) or (len(words) >= 8 and data >= 0.35):
        score += 2.5  # casi todo números: un volcado, una versión, una tabla de datos (1 505942 Aaron …)
    if _BLOCK_KW.match(t):
        score += 2.0
    if _MULTI_ASSIGN.match(t):
        score += 1.5
    if _ARITH.search(t):
        score += 1.0
    if (_FILE.search(t) or _BARE_FILE.search(t)) and len(words) <= 4:
        score += 2.0  # pestañas y rutas del editor: hello.py, docker-compose.yml, Dockerfile
    if len(words) >= 2 and sum(bool(_NUMBERED.match(w)) for w in words) / len(words) >= 0.4:
        score += 2.5  # linode1 linode3 mynewdirectory: un listado de archivos
    if _VIM.match(t):
        score += 3.0
    if len(_PATH.findall(t)) >= 2:
        score += 2.5  # /home/chuck:/bin/bash, src/app/main.py
    if _REGEX.match(t) or _SQL.match(t):
        score += 3.0  # /colou?r+/g · select * from players
    if _HTML.search(t) or _CSS.match(t):
        score += 2.5  # h1 class="title · <strong · .title { · background-color:
    if _FORMULA.search(t):
        score += 3.0  # una fórmula de Excel no se traduce
    if _YAML_KEY.match(t) or _HALF_ASSIGN.match(t):
        score += 2.0  # version: · result =
    if _DECL.match(t):
        score += 1.0  # const regex, def load
    if _SHELL.search(t):
        score += 4.0
    if _HEXID.search(t):
        score += 2.0
    if _DOCKER.match(t):
        score += 3.0
    if first in KEYWORDS:
        score += 0.5 if first in _SOFT else 1.5
    if len(words) == 1 and re.search(r"[._/:\\]|[a-z][A-Z]", t):
        score += 1.5  # un nombre suelto: GameStore.db, EFMigrationsHistory, src/app.py
    if re.search(r"[.!?]$", t) and len(words) >= 4 and sym < 0.04:
        score -= 1.5  # termina como una oración
    return score
