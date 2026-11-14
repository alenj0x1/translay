/* =====================================================================
   Colores de código: un resaltador propio (sin dependencias) y los temas de Ajustes › Apariencia.
   Sirve para lo que el video tiene escrito: bloques de código, comandos y comentarios del código,
   en la transcripción (web/js/screentext.js) y en el agente.

   highlight(text) → fragmento con <span class="tk-…">: comentario, texto, número, palabra clave,
   función, tipo, variable, etiqueta y atributo (HTML), prompt y opción de terminal, puntuación.
   Los temas son colores, aplicados como variables en :root (--code-bg, --tk-kw…).
   ===================================================================== */

const CODE_THEMES = {
  "vscode-dark": { name: "Visual Studio Code Dark", bg: "#1f1f1f", fg: "#cccccc", com: "#6a9955", str: "#ce9178",
    num: "#b5cea8", kw: "#569cd6", ctl: "#c586c0", fn: "#dcdcaa", ty: "#4ec9b0", var: "#9cdcfe", tag: "#569cd6",
    attr: "#9cdcfe", op: "#d4d4d4", prompt: "#6a9955", flag: "#9cdcfe" },
  "one-dark": { name: "One Dark", bg: "#282c34", fg: "#abb2bf", com: "#7f848e", str: "#98c379", num: "#d19a66",
    kw: "#c678dd", ctl: "#c678dd", fn: "#61afef", ty: "#e5c07b", var: "#e06c75", tag: "#e06c75", attr: "#d19a66",
    op: "#56b6c2", prompt: "#98c379", flag: "#d19a66" },
  "catppuccin-mocha": { name: "Catppuccin Mocha", bg: "#1e1e2e", fg: "#cdd6f4", com: "#9399b2", str: "#a6e3a1",
    num: "#fab387", kw: "#cba6f7", ctl: "#cba6f7", fn: "#89b4fa", ty: "#f9e2af", var: "#f38ba8", tag: "#89b4fa",
    attr: "#f9e2af", op: "#89dceb", prompt: "#a6e3a1", flag: "#fab387" },
  "catppuccin-latte": { name: "Catppuccin Latte", light: true, bg: "#eff1f5", fg: "#4c4f69", com: "#7c7f93",
    str: "#40a02b", num: "#fe640b", kw: "#8839ef", ctl: "#8839ef", fn: "#1e66f5", ty: "#df8e1d", var: "#d20f39",
    tag: "#1e66f5", attr: "#df8e1d", op: "#04a5e5", prompt: "#40a02b", flag: "#fe640b" },
  dracula: { name: "Dracula", bg: "#282a36", fg: "#f8f8f2", com: "#6272a4", str: "#f1fa8c", num: "#bd93f9",
    kw: "#ff79c6", ctl: "#ff79c6", fn: "#50fa7b", ty: "#8be9fd", var: "#f8f8f2", tag: "#ff79c6", attr: "#50fa7b",
    op: "#ff79c6", prompt: "#50fa7b", flag: "#ffb86c" },
  monokai: { name: "Monokai", bg: "#272822", fg: "#f8f8f2", com: "#88846f", str: "#e6db74", num: "#ae81ff",
    kw: "#f92672", ctl: "#f92672", fn: "#a6e22e", ty: "#66d9ef", var: "#fd971f", tag: "#f92672", attr: "#a6e22e",
    op: "#f92672", prompt: "#a6e22e", flag: "#fd971f" },
  nord: { name: "Nord", bg: "#2e3440", fg: "#d8dee9", com: "#616e88", str: "#a3be8c", num: "#b48ead",
    kw: "#81a1c1", ctl: "#81a1c1", fn: "#88c0d0", ty: "#8fbcbb", var: "#d8dee9", tag: "#81a1c1", attr: "#8fbcbb",
    op: "#81a1c1", prompt: "#a3be8c", flag: "#ebcb8b" },
  "github-light": { name: "GitHub Light", light: true, bg: "#f6f8fa", fg: "#1f2328", com: "#6e7781", str: "#0a3069",
    num: "#0550ae", kw: "#cf222e", ctl: "#cf222e", fn: "#8250df", ty: "#953800", var: "#953800", tag: "#116329",
    attr: "#0550ae", op: "#cf222e", prompt: "#116329", flag: "#0550ae" },
};
const CODE_THEME_DEFAULT = "vscode-dark";

// la otra versión de cada tema: el bloque de código sigue el modo de la app (claro u oscuro). Las oficiales
// cuando existen (Light+ de VS Code, One Light, Latte, GitHub Dark, Alucard de Dracula); Monokai y Nord, claras propias.
const CODE_PAIRS = {
  "vscode-dark": { light: true, bg: "#f7f7f7", fg: "#1f1f1f", com: "#008000", str: "#a31515", num: "#098658", kw: "#0000ff",
    ctl: "#af00db", fn: "#795e26", ty: "#267f99", var: "#001080", tag: "#800000", attr: "#e50000", op: "#3b3b3b",
    prompt: "#008000", flag: "#001080" },
  "one-dark": { light: true, bg: "#fafafa", fg: "#383a42", com: "#a0a1a7", str: "#50a14f", num: "#986801", kw: "#a626a4",
    ctl: "#a626a4", fn: "#4078f2", ty: "#c18401", var: "#e45649", tag: "#e45649", attr: "#986801", op: "#0184bc",
    prompt: "#50a14f", flag: "#986801" },
  "catppuccin-mocha": "catppuccin-latte",
  "catppuccin-latte": "catppuccin-mocha",
  dracula: { light: true, bg: "#fffbeb", fg: "#1f1f1f", com: "#6c664b", str: "#846e15", num: "#644ac9", kw: "#a3144d",
    ctl: "#a3144d", fn: "#14710a", ty: "#036a96", var: "#1f1f1f", tag: "#a3144d", attr: "#14710a", op: "#a3144d",
    prompt: "#14710a", flag: "#a34d14" },
  monokai: { light: true, bg: "#faf4f2", fg: "#29242a", com: "#918c8e", str: "#b8730a", num: "#7058be", kw: "#e14775",
    ctl: "#e14775", fn: "#269d69", ty: "#1c8ca8", var: "#d4572a", tag: "#e14775", attr: "#269d69", op: "#e14775",
    prompt: "#269d69", flag: "#d4572a" },
  nord: { light: true, bg: "#eceff4", fg: "#2e3440", com: "#7b88a1", str: "#4f7a37", num: "#8f5e8f", kw: "#5e81ac",
    ctl: "#5e81ac", fn: "#2f8396", ty: "#3f8885", var: "#2e3440", tag: "#5e81ac", attr: "#3f8885", op: "#5e81ac",
    prompt: "#4f7a37", flag: "#b0742a" },
  "github-light": { bg: "#0d1117", fg: "#e6edf3", com: "#8b949e", str: "#a5d6ff", num: "#79c0ff", kw: "#ff7b72",
    ctl: "#ff7b72", fn: "#d2a8ff", ty: "#ffa657", var: "#ffa657", tag: "#7ee787", attr: "#79c0ff", op: "#ff7b72",
    prompt: "#7ee787", flag: "#79c0ff" },
};

// el tema elegido en la versión del modo actual de la app
function codeThemeFor(key, light = document.documentElement.dataset.theme === "light") {
  const t = CODE_THEMES[key] || CODE_THEMES[CODE_THEME_DEFAULT];
  if (!!t.light === light) return t;
  const pair = CODE_PAIRS[key in CODE_THEMES ? key : CODE_THEME_DEFAULT];
  return (typeof pair === "string" ? CODE_THEMES[pair] : pair) || t;
}

function applyCodeTheme(key = prefs.code_theme) {
  const t = codeThemeFor(key);
  const s = document.documentElement.style;
  // en claro, blanco (un gris claro se ve sucio); en oscuro, el fondo del tema llevado al negro de la app: conserva
  // su tinte pero no queda como una caja gris más clara que los paneles
  s.setProperty("--code-bg", t.light ? "#ffffff" : `color-mix(in srgb, ${t.bg} 45%, #0f0f0f)`);
  s.setProperty("--code-fg", t.fg);
  for (const k of ["com", "str", "num", "kw", "ctl", "fn", "ty", "var", "tag", "attr", "op", "prompt", "flag"]) s.setProperty(`--tk-${k}`, t[k]);
  document.documentElement.classList.toggle("code-light", !!t.light);
}

// palabras clave de los lenguajes que más aparecen en cursos (Python, JS/TS, C#, Java, Go, Rust, SQL, shell)
const KW = new Set(("def class function func fn const let var return import from export as async await public private " +
  "protected static void int string bool float double char using namespace package struct enum interface impl " +
  "new lambda yield pub mut val type extends implements module require self this super null none true false nil " +
  "undefined in is not and or of select insert update delete create table where join on group by order having " +
  "into values set alter drop with echo export local readonly declare record is with").split(" "));
const CTL = new Set("if elif else for while do switch case break continue try catch except finally throw raise match then fi done esac goto".split(" "));
const TOKEN = new RegExp([
  /(?<com>#(?![!\[{])[^\n]*|\/\/[^\n]*|\/\*[\s\S]*?(?:\*\/|$)|<!--[\s\S]*?(?:-->|$)|(?<=^|\s)--\s[^\n]*)/,
  /(?<str>"(?:[^"\\\n]|\\.)*"?|'(?:[^'\\\n]|\\.)*'?|`(?:[^`\\]|\\.)*`?)/,
  /(?<prompt>^\s*(?:\$|>>>|\.\.\.|PS [^>\n]*>|[\w.-]+@[\w.-]+:[^\s$#]*[$#])(?=\s))/,
  /(?<tag><\/?[A-Za-z][\w-]*|\/?>)/,
  /(?<attr>\b[\w-]+(?==))/,
  /(?<flag>(?<=\s)--?[A-Za-z][\w-]*)/,
  /(?<var>\$\{?[A-Za-z_]\w*\}?|@[A-Za-z_]\w*)/,
  /(?<num>\b(?:0x[\da-fA-F]+|\d+(?:\.\d+)?(?:e[+-]?\d+)?)\b)/,
  /(?<word>[A-Za-z_][\w]*)/,
  /(?<op>[-+*\/%=<>!&|^~?:;,.(){}\[\]]+)/,
].map((r) => r.source).join("|"), "gm");

function highlight(text) {
  const frag = document.createDocumentFragment();
  let last = 0;
  const push = (s, cls) => {
    if (!s) return;
    if (!cls) { frag.append(s); return; }
    const sp = document.createElement("span");
    sp.className = `tk-${cls}`;
    sp.textContent = s;
    frag.append(sp);
  };
  for (const m of text.matchAll(TOKEN)) {
    push(text.slice(last, m.index));
    const g = m.groups;
    const s = m[0];
    if (g.word) {
      const lw = s.toLowerCase();
      const after = text.slice(m.index + s.length).match(/^\s*\(/);
      const cls = KW.has(lw) && (lw === s || s.toUpperCase() === s) ? "kw" : CTL.has(s) ? "ctl"
        : after ? "fn" : /^[A-Z][a-z0-9]+[A-Z]?\w*$/.test(s) ? "ty" : "";
      push(s, cls);
    } else {
      const cls = Object.keys(g).find((k) => g[k] !== undefined);
      push(s, cls);
    }
    last = m.index + s.length;
  }
  push(text.slice(last));
  return frag;
}

// muestra para Ajustes: C#, con un poco de todo para comparar temas (alto como la lista de temas)
const CODE_SAMPLE = `using System.Text.Json;

namespace Store.Api;

// load the configuration at startup
public record Config(string Host, int Port = 8080);

public static class Settings
{
    public static async Task<Config> LoadAsync(string path)
    {
        var json = await File.ReadAllTextAsync(path);
        var config = JsonSerializer.Deserialize<Config>(json);
        if (config is null) throw new InvalidDataException("empty config");
        return config with { Port = config.Port > 0 ? config.Port : 8080 };
    }
}

$ dotnet run --project Store.Api --urls http://localhost:5000`;
