"use strict";
// Translay: escenas ASCII para el fondo de la app (Ajustes › Apariencia › Fondo).
// Cada escena es una función de densidad: para cada celda (u de 0 a ASPECT, v de 0 a 1, en el tiempo t)
// devuelve [intensidad 0–1, tipo] y la celda se dibuja con el carácter de esa intensidad (RAMP). El tipo
// elige el color: 0 tinta del tema, 1 el protagonista (color de énfasis), 2 cálido, 3 su complemento.
// Los colores salen del tema (web/js/brand.js › tonePalette): pastel en claro, pastel intenso en oscuro.
// Agregar una escena = agregar una función a SCENES y su nombre en vt/prefs.py (home_bg).

const RAMP = " .·:-=+*#%@";
const ASPECT = 3.2;  // las escenas se diseñan para u de 0 a 3,2 (un lienzo 3,2 veces más ancho que alto)
const fract = (x) => x - Math.floor(x);
// valores de un cuadro: se calculan una vez por cuadro (no en cada una de las miles de celdas)
const FRAME = { t: NaN, data: {} };
function perFrame(t, key, make) {
  if (FRAME.t !== t) { FRAME.t = t; FRAME.data = {}; }
  return FRAME.data[key] || (FRAME.data[key] = make());
}
const hash2 = (a, b) => fract(Math.sin(a * 127.1 + b * 311.7) * 43758.5);

// un pez: cabeza redonda, ojo, agallas, escamas, aleta dorsal y pectoral, cola en horqueta que se mueve
function fishAt(px, py, cx, cy, s, dir, t) {
  if (Math.abs(px - cx) > s * 1.7 || Math.abs(py - cy) > s * 0.75) return null;  // lejos: nada que calcular
  const dx = (px - cx) * dir / s;
  let dy = (py - cy) / s;
  dy -= Math.sin(t * 6 + dx * 2) * 0.06 * Math.max(0, -dx);
  const taper = dx > 0 ? Math.sqrt(Math.max(0, 1 - dx * dx)) : Math.max(0, 1 + dx * 0.62);
  const h = 0.38 * taper * (dx > 0 ? 1 : Math.sqrt(Math.max(0, 1 - dx * dx * 0.3)));
  if (dx > -1 && dx < 1 && Math.abs(dy) < h) {
    const eye = (dx - 0.62) ** 2 + (dy + 0.1) ** 2;
    if (eye < 0.006) return 0;
    if (eye < 0.02) return 0.95;
    if (Math.abs(dx - 0.38) < 0.035 && Math.abs(dy) < h * 0.8) return 0.35;
    const scale = 0.75 + 0.25 * Math.sin(dx * 30 + Math.sin(dy * 30)) * Math.sin(dy * 28);
    return Math.min(1, (0.55 + (1 - Math.abs(dy) / h) * 0.4) * scale + (dy < 0 ? 0.08 : -0.05));
  }
  const tl = -1 - dx;
  if (tl > 0 && tl < 0.55 && Math.abs(dy) < tl * 0.95 + 0.06 && !(Math.abs(dy) < tl * 0.55 && tl > 0.22)) return 0.6 + Math.sin(dy * 40) * 0.15;
  if (dx > -0.35 && dx < 0.35 && dy < -h && dy > -h - 0.22 * (1 - Math.abs(dx) / 0.35) && dx < 0.2 - (-h - dy) * 0.8) return 0.45;
  if (dx > 0.05 && dx < 0.35 && dy > 0.05 && dy < 0.05 + (0.35 - dx) * 0.6 && dy > (dx - 0.05) * 0.4) return 0.5;
  return null;
}


// distancia de un punto a un segmento (patas, hilos)
function segDist(px, py, ax, ay, bx, by) {
  const dx = bx - ax, dy = by - ay;
  const k = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy || 1)));
  return Math.hypot(px - ax - dx * k, py - ay - dy * k);
}

// una araña: abdomen, cefalotórax y ocho patas de dos tramos (rodilla arriba); `step` las mueve al caminar
function spiderAt(px, py, cx, cy, s, step, cell) {
  if (Math.abs(px - cx) > s * 2.6 || Math.abs(py - cy) > s * 2.4) return null;  // lejos: nada que calcular
  const ab = ((px - cx) / (s * 0.62)) ** 2 + ((py - cy - s * 0.55) / (s * 0.78)) ** 2;
  if (ab < 1) return 0.9 + (1 - ab) * 0.1 - (Math.abs(px - cx) < s * 0.1 && py > cy + s * 0.2 ? 0.4 : 0);  // con una franja
  if (((px - cx) / (s * 0.42)) ** 2 + ((py - cy + s * 0.15) / (s * 0.38)) ** 2 < 1) return 0.95;
  if (Math.abs(px - cx) > s * 2.6 || Math.abs(py - cy) > s * 2.4) return null;
  const w = cell * 0.75;
  for (const side of [-1, 1]) {
    for (let i = 0; i < 4; i++) {
      const sway = Math.sin(step + i * 1.7 + (side > 0 ? 0 : Math.PI)) * s * 0.18;
      const hx = cx + side * s * 0.3, hy = cy - s * 0.25 + i * s * 0.17;
      const kx = hx + side * s * (1.0 + (i === 0 || i === 3 ? 0.15 : 0)), ky = hy - s * (0.75 - i * 0.28) + sway;
      const fx = kx + side * s * (0.55 + i * 0.1), fy = ky + s * (1.25 + i * 0.12) + sway * 0.5;
      if (segDist(px, py, hx, hy, kx, ky) < w || segDist(px, py, kx, ky, fx, fy) < w * 0.85) return 0.7;
    }
  }
  return null;
}

// una telaraña: radios y una espiral de tramos rectos entre radio y radio, con gotas de rocío que brillan
function webAt(px, py, cx, cy, R, N, t, seed, cell) {
  const dx = px - cx, dy = py - cy, r = Math.hypot(dx, dy);
  if (r > R) return null;
  const a = Math.atan2(dy, dx) + seed, sector = (2 * Math.PI) / N;
  const local = ((a % sector) + sector) % sector - sector / 2;  // ángulo dentro del sector, centrado
  if (Math.abs(Math.sin(local)) * r < cell * 0.4 && r > 0.012) return [0.34 + 0.12 * (1 - r / R), 0];  // radio
  const along = r * Math.cos(local) / Math.cos(sector / 2);  // la espiral: polígono entre radios
  const gap = R / 6.5;
  const ring = (along - 0.03) / gap;
  const nearest = Math.round(ring);
  if (nearest >= 1 && Math.abs(ring - nearest) * gap < cell * 0.38) {
    const node = Math.abs(local) > sector * 0.38;  // cerca de un radio: donde se juntan, una gota
    const glint = node && hash2(Math.round(a / sector + seed * 10), nearest) > 0.88;
    if (glint) return [0.85 + 0.15 * Math.sin(t * 2 + nearest + a * 5), Math.sin(t * 1.3 + nearest * 3 + a * 7) > 0.6 ? 2 : 0];
    return [0.3, 0];
  }
  return null;
}

// los íconos de la escena Translay: formas en coordenadas propias (de -1 a 1), devuelven la intensidad o 0
const sdBox = (x, y, bx, by, r) => {  // distancia a una caja redondeada de medio ancho bx y medio alto by
  const qx = Math.abs(x) - bx + r, qy = Math.abs(y) - by + r;
  return Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0) - r;
};
const ICON_SHAPES = {
  nota(x, y, th) {  // una corchea: cabeza inclinada, plica y bandera
    const hx = (x + 0.3) * 0.8 + (y - 0.55) * 0.45, hy = (y - 0.55) * 0.8 - (x + 0.3) * 0.45;
    if (hx * hx / 0.13 + hy * hy / 0.05 < 1) return 0.85;
    if (Math.abs(x - 0.05) < th * 1.1 && y > -0.85 && y < 0.5) return 0.8;
    if (x > 0.05 && x < 0.6 && Math.abs(y - (-0.85 + (x - 0.05) * 0.9 + (x - 0.05) ** 2 * 0.6)) < th * 1.6) return 0.75;
    return 0;
  },
  video(x, y, th) {  // la pantalla de un video con su triángulo de reproducir
    if (Math.abs(sdBox(x, y, 1, 0.7, 0.18)) < th) return 0.75;
    const tx = x + 0.15;
    if (tx > -0.25 && tx < 0.45 && Math.abs(y) < (0.45 - tx) * 0.62) return 0.85;
    return 0;
  },
  clase(x, y, th) {  // un birrete: el tablero, la base y la borla
    if (Math.abs(x) + Math.abs(y + 0.25) * 2.4 < 1 && Math.abs(x) + Math.abs(y + 0.25) * 2.4 > 1 - th * 2.6) return 0.8;
    if (Math.abs(x) < 0.55 && y > 0.05 && y < 0.5 && (Math.abs(Math.abs(x) - 0.55) < th || Math.abs(y - 0.5) < th)) return 0.7;
    if (Math.abs(x - 0.8) < th && y > -0.2 && y < 0.45) return 0.65;
    if ((x - 0.8) ** 2 + (y - 0.55) ** 2 < 0.02) return 0.8;
    return 0;
  },
  agente(x, y, th) {  // la cabeza del agente: cara, ojos y antena
    if (Math.abs(sdBox(x, y + 0.1, 0.85, 0.65, 0.3)) < th) return 0.75;
    if ((x + 0.35) ** 2 + (y + 0.05) ** 2 < 0.025 || (x - 0.35) ** 2 + (y + 0.05) ** 2 < 0.025) return 0.9;
    if (Math.abs(y - 0.3) < th * 0.9 && Math.abs(x) < 0.3) return 0.6;
    if (Math.abs(x) < th && y < -0.75 && y > -1.05) return 0.7;
    if (x * x + (y + 1.1) ** 2 < 0.02) return 0.8;
    return 0;
  },
  micro(x, y, th) {  // un micrófono: cápsula, soporte y pie
    if (sdBox(x, y + 0.3, 0.32, 0.55, 0.32) < 0) return 0.8;
    const r = Math.hypot(x, y + 0.2);
    if (y > -0.2 && Math.abs(r - 0.6) < th) return 0.7;
    if (Math.abs(x) < th && y > 0.4 && y < 0.85) return 0.7;
    if (Math.abs(y - 0.88) < th && Math.abs(x) < 0.35) return 0.7;
    return 0;
  },
  subtitulos(x, y, th) {  // una caja con dos líneas de subtítulo
    if (Math.abs(sdBox(x, y, 1, 0.68, 0.16)) < th) return 0.75;
    if (Math.abs(y - 0.15) < th * 1.2 && x > -0.65 && x < 0.65 && Math.sin(x * 9) > -0.6) return 0.8;
    if (Math.abs(y - 0.4) < th * 1.2 && x > -0.4 && x < 0.4) return 0.8;
    return 0;
  },
  idiomas(x, y, th) {  // un globo terráqueo: contorno, meridiano y paralelos
    const r = Math.hypot(x, y);
    if (Math.abs(r - 0.9) < th) return 0.75;
    if (r < 0.9 && (Math.abs(Math.hypot(x / 0.42, y) - 0.9) < th * 1.6 || Math.abs(y) < th * 0.9 || Math.abs(Math.abs(y) - 0.45) < th * 0.9)) return 0.6;
    return 0;
  },
  charla(x, y, th) {  // un globo de conversación con tres puntos
    if (Math.abs(sdBox(x, y + 0.1, 0.95, 0.6, 0.35)) < th) return 0.75;
    if (y > 0.45 && y < 0.95 && Math.abs(x + 0.45 - (y - 0.45) * 0.3) < th * 1.3) return 0.7;
    for (const dx of [-0.42, 0, 0.42]) if ((x - dx) ** 2 + (y + 0.1) ** 2 < 0.025) return 0.85;
    return 0;
  },
};
// tipo, u, v, tamaño (en altos de pantalla), protagonista; repartidos para cualquier ancho (la escena se recorta al centro)
// tipo, lugar a lo ancho (de -1, el borde izquierdo que se ve, a 1, el derecho), alto (0 arriba, 1 abajo), tamaño (en altos
// de pantalla) y si va en el color del tema; repartidos a mano alrededor del isotipo, sin cuadrícula
const TRANSLAY_ICONS = [
  ["nota", -0.62, 0.2, 0.085, 0], ["video", 0.6, 0.17, 0.09, 1], ["clase", -0.52, 0.82, 0.09, 0], ["agente", 0.58, 0.83, 0.09, 0],
  ["micro", -0.88, 0.5, 0.08, 1], ["subtitulos", 0.9, 0.5, 0.085, 0], ["idiomas", -0.18, 0.1, 0.075, 0], ["charla", 0.2, 0.9, 0.08, 1],
  ["nota", 0.9, 0.88, 0.07, 0], ["video", -0.92, 0.85, 0.075, 0], ["idiomas", 0.92, 0.12, 0.075, 1], ["clase", -0.92, 0.14, 0.075, 1],
];

// un perrito peludo (tipo poodle) de perfil mirando a la derecha, con su camiseta, en coordenadas propias (alto ~1):
// todo es pelo rizado (bordes irregulares y textura de rulos), cabeza grande con orejas caídas, hocico corto, patas
// cortas que se mueven al caminar (step), un pompón de cola (wag) y la cabeza que se inclina un poco (tilt)
function fluff(x, y, cx, cy, rx, ry, seed) {  // una mota de pelo: elipse con el borde ondulado como rulos
  const dx = (x - cx) / rx, dy = (y - cy) / ry, a = Math.atan2(dy, dx);
  return Math.hypot(dx, dy) < 1 + 0.13 * Math.sin(a * 9 + seed) + 0.06 * Math.sin(a * 17 + seed * 2);
}
const curls = (x, y) => 0.62 + 0.3 * Math.sin(x * 23 + Math.sin(y * 19) * 2) * Math.sin(y * 21 + Math.sin(x * 17));  // textura de rulos
function dogAt(x, y, step, wag, tilt) {
  // la cabeza (con orejas, ojo, nariz y hocico) se inclina alrededor del cuello
  const px = 0.45, py = -0.3, c = Math.cos(tilt), s = Math.sin(tilt);
  const hx = px + (x - px) * c + (y - py) * s, hy = py - (x - px) * s + (y - py) * c;
  if ((hx - 0.93) ** 2 + (hy + 0.66) ** 2 < 0.0045) return [0, 0];                     // el ojo, oscuro y redondo
  if ((hx - 1.27) ** 2 + (hy + 0.47) ** 2 < 0.007) return [1, 0];                      // la nariz
  if (fluff(hx, hy, 1.12, -0.44, 0.17, 0.13, 3)) return [0.55 + 0.2 * curls(hx, hy), 0];  // el hocico, más corto el pelo
  if (fluff(hx, hy, 0.55, -0.2, 0.2, 0.42, 1)) return [0.9 * curls(hx * 1.3, hy), 0];       // la oreja caída, rizada
  if (fluff(hx, hy, 0.78, -0.62, 0.44, 0.42, 5)) return [curls(hx, hy), 0];                 // la cabeza, grande y peluda
  // la camiseta: cubre el pecho y la espalda, con su manga
  const inShirt = fluff(x, y, 0.08, 0.02, 0.58, 0.42, 7);
  if (inShirt && x > -0.38) return [0.62 + 0.18 * Math.sin(y * 14 + x * 3), 2];
  if (fluff(x, y, 0.45, 0.28, 0.17, 0.2, 2) && y > 0.15) return [0.66, 2];               // la manga
  // el cuerpo peludo (la parte de atrás, sin camiseta) y el pompón de la cola
  if (fluff(x, y, -0.1, 0.05, 0.72, 0.46, 9)) return [curls(x, y), 0];
  if (fluff(x, y, -0.86, -0.32 + wag * 0.08, 0.2, 0.2, 4)) return [curls(x * 1.2, y), 0];
  // las patas: cortas y peludas, se alternan al caminar
  for (const [lx, ph] of [[-0.52, 0], [-0.28, Math.PI], [0.22, Math.PI], [0.46, 0]]) {
    const sw = Math.sin(step + ph) * 0.14;
    const fx = lx + sw, top = 0.3, bot = 0.92;
    const k = Math.max(0, Math.min(1, (y - top) / (bot - top)));
    const cxl = lx + (fx - lx) * k;
    if (y > top && y < bot + 0.04 && Math.abs(x - cxl) < 0.11 + 0.025 * Math.sin(y * 30 + lx * 9)) return [curls(x, y) * 0.95, 0];
  }
  return null;
}

// un gatito sentado de frente, blanco con manchas atigradas (en la cabeza y una mejilla) y una manchita en la nariz,
// en coordenadas propias (de -1, la punta de las orejas, a 1, el suelo): parpadea despacio (blink de 0 a 1), mueve la
// cola (sway) y, cuando suena el juguete, mueve las orejas (twitch)
const inTri = (x, y, ax, ay, bx, by, cx, cy) => {
  const d1 = (x - bx) * (ay - by) - (ax - bx) * (y - by), d2 = (x - cx) * (by - cy) - (bx - cx) * (y - cy), d3 = (x - ax) * (cy - ay) - (cx - ax) * (y - ay);
  return !((d1 < 0 || d2 < 0 || d3 < 0) && (d1 > 0 || d2 > 0 || d3 > 0));
};
function catAt(x, y, blink, sway, twitch, th, eyeX = 0.19) {
  const tabby = (a, b) => [0.6 + 0.32 * (Math.sin(a * 26 + Math.sin(b * 9) * 1.5) > 0.15 ? 1 : 0), 2];  // atigrado: rayas
  // las manchas de la cara (como en la foto): una franja arriba del ojo derecho y la manchita sobre la naricita; el
  // resto, blanco
  const patch = (a, b) =>
    // la gorrita: el pelo atigrado de arriba de la cabeza, que baja un poco más del lado derecho hasta encima del ojo
    (b < -0.53 + Math.max(0, a) * 0.22 && a > -0.3)
    // la manchita: un triángulo que nace angosto en la naricita y se abre hacia arriba entre los ojos, del lado
    // derecho (casi roza ese ojo), hasta un poco más arriba de los ojos
    || (b > -0.42 && b < -0.16 && a > -0.02 - (-0.16 - b) * 0.12 && a < 0.04 + (-0.16 - b) * 0.42);
  // los ojos: almendrados, con el borde oscuro, el iris del color del tema, la pupila en rendija y un brillo arriba
  for (const ex of [-eyeX, eyeX]) {
    const ry = 0.075 * (1 - blink) + 0.006;
    const q = ((x - ex) / 0.105) ** 2 + ((y + 0.32) / ry) ** 2;
    if (q < 1) {
      if (blink > 0.6) return [0.85, 0];                                          // cerrado: una línea
      if (Math.abs(x - ex) < th * 0.5) return [0.04, 0];                          // la pupila: una columna exacta
      if (q > 0.72) return [0.98, 0];                                             // el borde del ojo
      if ((x - ex - 0.045) ** 2 + (y + 0.355) ** 2 < 0.0009) return [1, 0];      // el brillo
      return [0.85, 1];                                                           // el iris
    }
  }
  // la naricita: rosada, con su raya al medio, separada de la manchita por un borde vacío
  if (inTri(x, y, -0.08, -0.155, 0.08, -0.155, 0, -0.065)) return Math.abs(x) < th * 0.4 && y > -0.11 ? [0.4, 3] : [1, 3];
  if (inTri(x, y, -0.105, -0.17, 0.105, -0.17, 0, -0.045)) return [0, 0];
  // la trompa: dos almohadillas blancas con los puntitos de donde salen los bigotes, la boca en «w» y la barbilla
  for (const side of [-1, 1]) {
    const pdx = x - side * 0.1, pdy = y + 0.02;
    if ((pdx / 0.12) ** 2 + (pdy / 0.08) ** 2 < 1) {
      for (const [dx, dy] of [[0.0, -0.02], [0.05, 0.0], [0.02, 0.03]]) if ((pdx - side * dx) ** 2 + (pdy - dy) ** 2 < 0.0004) return [0.45, 0];
      return [0.86, 0];
    }
  }
  if (y > -0.05 && y < 0.01 && Math.abs(Math.abs(x) - 0.03 - Math.abs(y + 0.02) * 0.6) < th * 0.6 && Math.abs(x) < 0.07) return [0.4, 0];
  // bigotes: salen de los cachetes, lejos de la nariz y la trompa, finos y tenues
  for (const side of [-1, 1]) for (const [dy, ey] of [[-0.06, -0.12], [-0.01, 0.0]]) {
    if (segDist(x, y, side * 0.24, dy, side * 0.7, ey) < th * 0.3) return [0.18, 0];
  }
  // las orejas: con la punta redondeada, el interior rosado con pelitos; se mueven un poco cuando escuchan
  for (const side of [-1, 1]) {
    const tw = side * twitch * 0.06;
    if (inTri(x * side, y, 0.14, -0.58, 0.42, -0.42, 0.33 + tw, -0.82) && Math.hypot(x * side - 0.33 - tw, y + 0.8) > 0.02) {
      if (inTri(x * side, y, 0.2, -0.56, 0.37, -0.46, 0.31 + tw, -0.72)) return Math.sin(x * 60) > 0.6 ? [0.75, 0] : [0.5, 1];
      return side > 0 ? tabby(x, y) : [0.78, 0];
    }
  }
  // la cabeza: redonda y un poco más ancha en los cachetes, con pelo suave; la mancha atigrada donde va
  if ((x / 0.5) ** 2 + ((y + 0.3) / 0.4) ** 2 < 1) {
    if (patch(x, y)) return tabby(x, y);
    return [0.72 + 0.06 * Math.sin(x * 34 + y * 22) * Math.sin(y * 18), 0];
  }
  // el cuerpo sentado (más chico que la cabeza, como un gatito), el pecho blanco, las patitas y la cola que se mueve
  const wB = 0.26 + 0.16 * Math.max(0, Math.min(1, (y - 0.05) / 0.85));
  if (y > 0.05 && y < 0.95 && Math.abs(x) < wB) return x > 0.16 && y < 0.5 ? tabby(x, y) : [0.72 + 0.04 * Math.sin(y * 25 + x * 14), 0];
  for (const fx of [-0.12, 0.12]) if (((x - fx) / 0.1) ** 2 + ((y - 0.93) / 0.075) ** 2 < 1) return [0.82, 0];
  for (let i = 0; i < 14; i++) {  // la cola: sale de atrás y se curva hacia arriba, moviéndose
    const k = i / 13, tx = 0.36 + k * 0.36 + Math.sin(k * 3 + sway) * 0.08 * k, ty = 0.85 - k * 0.7 + Math.sin(k * 2 + sway) * 0.05;
    if (Math.hypot(x - tx, y - ty) < 0.07 - k * 0.02) return k > 0.6 ? tabby(x, y) : [0.72, 0];
  }
  return null;
}

const SEA_ROCKS = [[0.35, 0.78, 0.09, 0.1], [2.4, 0.8, 0.12, 0.08], [2.6, 0.75, 0.06, 0.12]];
const SEA_FISH = [[0.06, 0.38, 0.11, 1, 1], [0.05, 0.55, 0.07, -1, 0], [0.04, 0.3, 0.06, 1, 0], [0.035, 0.48, 0.055, 1, 0], [0.03, 0.62, 0.05, -1, 0]];
const KELP = Array.from({ length: 9 }, (_, s) => [0.15 + s * 0.36 + hash2(s, 1) * 0.1, 0.35 + hash2(s, 2) * 0.35]);
const WEBS = [[0.75, 0.45, 0.38, 14, 0.2], [2.7, 0.3, 0.3, 12, 1.1], [1.85, 0.82, 0.2, 10, 2.3]];
const HANGING = [[1.35, 0.42, 0.06, 0, 1], [2.15, 0.3, 0.045, 2.1, 0], [3.05, 0.62, 0.05, 4.2, 0]];
const JELLIES = [[0.6, 0.42, 0.16, 0], [1.75, 0.3, 0.22, 1.7], [2.75, 0.5, 0.13, 3.1]];

const SCENES = {
  // translay: el isotipo (la onda de voz del logo) grande y hablando en el centro y, regados alrededor por todo el
  // espacio, lo que Translay toca: una nota musical, un video, una clase, el agente, un micrófono, subtítulos,
  // idiomas, una conversación. Flotan despacio, cada uno a su ritmo. La escena por defecto.
  translay(u, v, t, cell, A = ASPECT) {
    const cx = 1.6, cy = 0.5;
    let w = 0.03 + 0.025 * Math.sin(u * 2.3 + v * 4 + t * 0.25), k = 0;
    // el isotipo: las cinco barras del logo, grandes, en el color del tema
    const BW = 0.085, GAP = 0.058, H = [0.44, 0.84, 0.6, 1, 0.44];
    if (Math.abs(u - cx) < 0.4 && Math.abs(v - cy) < 0.3) {
      const x0 = cx - (H.length * BW + (H.length - 1) * GAP) / 2 + BW / 2;
      for (let i = 0; i < H.length; i++) {
        const talk = 0.72 + 0.28 * Math.sin(t * 2.4 + i * 1.7) * Math.sin(t * 0.8 + i * 0.6);
        const h = 0.5 * H[i] * talk, bx = x0 + i * (BW + GAP);
        const dy = Math.max(0, Math.abs(v - cy) - h / 2);   // cada barra es una cápsula: segmento vertical con radio BW/2
        const d = Math.hypot(u - bx, dy);
        if (d < BW / 2) return [0.78 + 0.22 * (1 - d / (BW / 2)), 1];
      }
      return [w, 0];
    }
    // lo que lo rodea: cada ícono en su lugar (repartidos a mano, sin cuadrícula), flotando
    const icons = perFrame(t, "iconos", () => TRANSLAY_ICONS.map(([, fx, py], n) => {
      const half = Math.min(A, ASPECT) / 2 - 0.12;  // medio ancho visible, con margen
      return [cx + fx * half + Math.cos(t * 0.23 + n * 1.9) * 0.025, py + Math.sin(t * 0.31 + n * 2.7) * 0.03];
    }));
    for (let n = 0; n < TRANSLAY_ICONS.length; n++) {
      const [kind, , , size, hot] = TRANSLAY_ICONS[n];
      const lx = (u - icons[n][0]) / size, ly = (v - icons[n][1]) / size;
      if (Math.abs(lx) > 1.25 || Math.abs(ly) > 1.25) continue;
      const f = ICON_SHAPES[kind](lx, ly, (cell / size) * 0.75);
      if (f) return [f, hot ? 1 : 3];
    }
    return [w, k];
  },

  // fondo marino: luz en la superficie, peces, cardumen, algas, rocas, arena y burbujas
  mar(u, v, t) {
    let w = 0, k = 0;
    if (v < 0.2) {
      const ca = Math.sin(u * 9 + t * 0.8 + Math.sin(v * 20 + t)) * Math.sin(u * 4 - t * 0.6 + v * 12);
      w = Math.max(0, ca) * 0.35 * (1 - v * 4) + (v < 0.04 ? 0.25 + 0.15 * Math.sin(u * 12 + t * 2) : 0);
    }
    w = Math.max(w, 0.04 + 0.04 * Math.sin(u * 3 + v * 5 + t * 0.3));
    const sand = 0.86 + Math.sin(u * 2.1) * 0.03 + Math.sin(u * 7) * 0.01;
    if (v > sand) return [0.3 + 0.2 * Math.sin(u * 40 + Math.sin(v * 30) * 2) * Math.sin(v * 60), 0];
    for (const r of SEA_ROCKS) {
      if (((u - r[0]) / r[2]) ** 2 + ((v - r[1]) / r[3]) ** 2 < 1 && v < sand + 0.02) w = Math.max(w, 0.5 + 0.25 * Math.sin(u * 50) * Math.sin(v * 40));
    }
    for (let s = 0; s < 9; s++) {
      const [bx, len] = KELP[s];
      if (Math.abs(u - bx) > 0.09) continue;  // lejos de esta alga
      if (v > sand - len && v < sand) {
        const p = (sand - v) / len, off = Math.sin(v * 14 - t * 1.2 + s) * 0.04 * p;
        if (Math.abs(u - bx - off) < 0.012 + 0.008 * Math.sin(v * 40 + s)) { w = Math.max(w, 0.55 - p * 0.2); k = 2; }
        if (s % 3 === 0 && Math.abs(u - bx - off - 0.025 * Math.sin(v * 30 + s)) < 0.03 && Math.sin(v * 35 + s) > 0.7) w = Math.max(w, 0.5);
      }
    }
    const bubbles = perFrame(t, "burbujas", () => Array.from({ length: 6 }, (_, b) =>
      [0.5 + b * 0.5 + Math.sin(t * 1.5 + b) * 0.02, 1 - fract(t * 0.08 + hash2(b, 3))]));
    for (let b = 0; b < 6; b++) {
      const [bx, by] = bubbles[b];
      if (Math.abs(u - bx) > 0.02 || Math.abs(v - by) > 0.02) continue;
      const dd = Math.hypot(u - bx, v - by);
      if (dd < 0.018 && dd > 0.008) w = Math.max(w, 0.7);
    }
    const fish = perFrame(t, "peces", () => SEA_FISH.map((p, i) => {
      const run = (t * p[0] + hash2(i, 5) * 3.4) % 3.9;
      return [p[3] > 0 ? run - 0.35 : 3.55 - run, p[1] + Math.sin(t * 0.7 + i) * 0.02, p[2] * 2, p[3], p[4]];
    }).concat(Array.from({ length: 7 }, (_, s) => [((t * 0.05 + 0.6) % 3.9) - 0.3 + (s % 3) * 0.07,
      0.2 + Math.floor(s / 3) * 0.05 + Math.sin(t + s) * 0.01, 0.035, 1, -1])));
    for (let i = 0; i < fish.length; i++) {
      const [fx, fy, fs, dir, hot] = fish[i];
      const f = fishAt(u, v, fx, fy, fs, dir, hot < 0 ? t + i : t);
      if (f !== null) { if (hot < 0) { w = Math.max(w, f * 0.8); k = 0; } else { w = f; k = hot && f > 0.3 ? 1 : 0; } }
    }
    return [w, k];
  },

  // atardecer: sol con franjas que se hunde, halo, nubes, gaviotas, olas en perspectiva y el reflejo
  atardecer(u, v, t) {
    const hz = 0.56, sx = 1.6, sy = hz + 0.02, R = 0.3;
    let w = 0, k = 0;
    if (v < hz) {
      const d = Math.hypot(u - sx, v - sy);
      w = 0.05 + (v / hz) * 0.18;
      if (d < R) {
        const band = (v - (sy - R)) / R;
        const gap = v > sy - R * 0.55 && fract((v - sy) * 28 + t * 0.15) < (band - 0.45) * 0.55;
        if (!gap) { w = 0.95 - d * 0.6; k = 1; } else w = 0.12;
      } else if (d < R + 0.12) { w = Math.max(w, 0.35 * (1 - (d - R) / 0.12)); k = 2; }
      const cl = Math.sin(u * 2 + t * 0.05) * 0.5 + Math.sin(u * 5.3 - t * 0.07) * 0.3;
      for (let q = 0; q < 3; q++) {
        const cyv = 0.18 + q * 0.11 + Math.sin(u * 1.3 + q) * 0.02;
        const thick = 0.015 + 0.02 * Math.max(0, Math.sin(u * 1.7 + q * 2 + t * 0.03));
        if (Math.abs(v - cyv) < thick && cl + q * 0.2 > -0.1) { w = Math.max(w, 0.4 + 0.25 * Math.sin(u * 30)); k = Math.abs(u - sx) < 0.8 ? 2 : 0; }
      }
      for (let b = 0; b < 3; b++) {
        const bx = ((t * 0.06 + b * 0.9) % 4) - 0.4, by = 0.12 + b * 0.07 + Math.sin(t + b) * 0.01;
        const dx = u - bx, dy = v - by;
        if (Math.abs(dx) < 0.04 && Math.abs(dy + Math.abs(dx) * 0.6 * (1 + 0.4 * Math.sin(t * 6 + b))) < 0.008) { w = 0.8; k = 0; }
      }
      return [w, k];
    }
    const p = (v - hz) / (1 - hz);
    const lines = Math.sin((1 / (p + 0.08)) * 6 - t * 1.2) * 0.5 + 0.5;
    w = 0.08 + lines * 0.25 * (1 - p * 0.4);
    if (Math.abs(u - sx) < 0.12 + p * 0.55) {
      const g = fract(Math.sin(Math.floor((u - sx) / 0.03) * 12.9 + Math.floor(1 / (p + 0.05) * 3)) * 400 + t * 1.5);
      if (g > 0.45 && lines > 0.3) { w = 0.6 + g * 0.4; k = 1; }
    }
    if (v < hz + 0.012) w = Math.max(w, 0.45);
    return [w, k];
  },

  // arañas: telarañas con rocío, arañas que cuelgan de su hilo y suben y bajan, una que camina por la telaraña
  "arañas"(u, v, t, cell) {
    let w = 0.03 + 0.03 * Math.sin(u * 2 + v * 3 + t * 0.2), k = 0;
    if (v < 0.035 + Math.sin(u * 3) * 0.01) return [0.45 + 0.15 * Math.sin(u * 40), 0];  // la rama de arriba
    for (let q = 0; q < WEBS.length; q++) {
      const [cx, cy, R, N, seed] = WEBS[q];
      if (Math.abs(u - cx) > R || Math.abs(v - cy) > R) continue;  // lejos de esta telaraña
      const r = webAt(u, v, cx, cy, R, N, t, seed, cell);
      if (r && r[0] > w) { w = r[0]; k = r[1]; }
    }
    // las que cuelgan: el hilo desde la rama y la araña subiendo y bajando
    const hang = perFrame(t, "colgadas", () => HANGING.map(([x, base, , ph]) => [x + Math.sin(t * 0.7 + ph) * 0.01, base + Math.sin(t * 0.5 + ph) * 0.12]));
    for (let q = 0; q < HANGING.length; q++) {
      const [, , s, ph, hot] = HANGING[q], [sx, y] = hang[q];
      if (Math.abs(u - sx) > s * 2.7) continue;  // lejos de esta araña y de su hilo
      if (v < y - s * 0.4 && Math.abs(u - sx) < cell * 0.45) w = Math.max(w, 0.35);
      const f = spiderAt(u, v, sx, y, s, t * 3 + ph, cell);
      if (f !== null) { w = f; k = hot && f > 0.5 ? 1 : 0; }
    }
    // la que camina: da vueltas por la telaraña grande
    const ang = t * 0.12, cx = 0.75 + Math.cos(ang) * 0.24, cy = 0.45 + Math.sin(ang) * 0.24;
    const f = spiderAt(u, v, cx, cy, 0.045, t * 9, cell);
    if (f !== null) { w = f; k = 0; }
    return [w, k];
  },

  // arañas y perro: la escena de las arañas y, abajo, un perrito que camina; a mitad de camino suena un juguete, se
  // detiene, inclina la cabeza para escuchar y sigue caminando. Un gatito sentado mira, parpadea y mueve las orejas. En bucle.
  "arañas y perro"(u, v, t, cell, A = ASPECT) {
    const left = Math.max(0, (ASPECT - A) / 2), right = left + Math.min(A, ASPECT);  // lo que se ve a lo ancho
    const mid = (left + right) / 2, ground = 0.93, size = 0.17;
    const T = 18, p = fract(t / T);
    // el recorrido: entra por la izquierda, se detiene a mitad (0.4–0.62) y sale por la derecha
    const walkIn = Math.min(1, p / 0.4), walkOut = Math.max(0, (p - 0.62) / 0.38);
    const x = p < 0.62 ? left - 0.4 + (mid - 0.25 - left + 0.4) * walkIn : mid - 0.25 + (right + 0.4 - mid + 0.25) * walkOut;
    const walking = p < 0.4 || p > 0.62;
    const ease = (a, b) => { const k = Math.max(0, Math.min(1, (p - a) / (b - a))); return k * k * (3 - 2 * k); };
    const tilt = -0.42 * (ease(0.43, 0.47) - ease(0.56, 0.6));  // la cabeza: se inclina, escucha y vuelve
    const step = walking ? t * 7 : 0;
    const wag = Math.sin(t * (walking ? 6 : 11));
    // el juguete: una pelota en el suelo, más adelante; cuando suena, sus ondas
    const toyX = mid + 0.28;
    if ((u - toyX) ** 2 + (v - ground + 0.035) ** 2 < 0.035 ** 2) return [0.9, 1];
    if (p > 0.4 && p < 0.52) {
      const r = Math.hypot(u - toyX, v - ground + 0.035), q = (p - 0.4) / 0.12;
      for (const R of [0.06, 0.09, 0.12]) if (Math.abs(r - R - q * 0.03) < cell * 0.7 && v < ground - 0.02 && u > toyX - 0.05) return [0.65 * (1 - q), 1];
    }
    // el perrito
    const lx = (u - x) / size, ly = (v - (ground - size * 0.96)) / size;
    if (lx > -1.2 && lx < 1.45 && ly > -1.15 && ly < 1.0) {
      const d = dogAt(lx, ly, step, wag, tilt);
      if (d) return d;
    }
    // el gatito: sentado del otro lado del juguete, parpadea despacio, mueve la cola y las orejas cuando suena
    // el gatito va alineado a la cuadrícula de caracteres y sus ojos a un número entero de columnas del centro: así
    // los dos ojos caen igual en las celdas y la pupila se ve idéntica en ambos
    const gcols = Math.ceil(A / cell), gstep = A / gcols, u0g = Math.max(0, (ASPECT - A) / 2);
    const csize = 0.2, catX = u0g + Math.round((mid + 0.62 - u0g) / gstep) * gstep;
    const eyeX = Math.max(1, Math.round(0.19 * csize / gstep)) * gstep / csize;
    const cx2 = (u - catX) / csize, cy2 = (v - (ground - csize)) / csize;
    if (cx2 > -0.85 && cx2 < 0.95 && cy2 > -1.05 && cy2 < 1.0) {
      const blink = Math.max(0, 1 - Math.abs(fract(t / 5.5) - 0.5) * 18);   // un parpadeo lento cada 5,5 s
      const twitch = p > 0.4 && p < 0.5 ? Math.sin((p - 0.4) * 120) : 0;
      const c = catAt(cx2, cy2, blink, t * 1.3, twitch, gstep / csize, eyeX);
      if (c) return c;
    }
    if (Math.abs(v - ground) < 0.006 && Math.sin(u * 60) > 0) return [0.3, 0];  // el suelo
    return SCENES["arañas"](u, v, t, cell);
  },

  // medusas: campana que late con nervaduras, brazos ondulantes, tentáculos, rayos de luz y partículas
  medusas(u, v, t, cell) {
    let w = 0.03 + v * 0.04, k = 0;
    const ray = Math.max(0, Math.sin((u + v * 0.6) * 5 + t * 0.15)) * Math.max(0, Math.sin((u + v * 0.6) * 1.3 - t * 0.05));
    w += ray * 0.18 * (1 - v);
    if (hash2(Math.floor(u * 60), Math.floor((v + t * 0.01) * 30)) > 0.985) w = Math.max(w, 0.4);
    for (let i = 0; i < JELLIES.length; i++) {
      const J = JELLIES[i];
      if (Math.abs(u - J[0]) > J[2] * 1.5 || v < J[1] - J[2] || v > J[1] + J[2] * 4.6) continue;  // lejos de esta medusa
      const pulse = Math.sin(t * 1.6 + J[3]);
      const s = J[2], cx = J[0] + Math.sin(t * 0.3 + i) * 0.04, cy = J[1] - pulse * 0.015 + Math.sin(t * 0.4 + i) * 0.03;
      const rw = s * (1 - pulse * 0.08), rh = s * 0.62 * (1 + pulse * 0.06);
      const dx = u - cx, dy = v - cy;
      const rim = 0.012 * Math.sin(dx / rw * 18) + 0.02;
      const e = (dx * dx) / (rw * rw) + (dy * dy) / (rh * rh);
      if (dy < rim && e < 1) {
        const merid = Math.abs(Math.sin(Math.atan2(dy, dx) * 7)) < 0.25 ? 0.25 : 0;
        return [Math.max(w, 0.5 + merid + (e > 0.8 ? 0.3 : 0) - (dy > -rh * 0.3 && e < 0.5 ? 0.15 : 0)), 1];
      }
      const yy = dy - rim;
      for (let a = -1; a <= 1; a++) {
        const L = s * 2.1;
        if (yy > 0 && yy < L) {
          const q = yy / L, off = a * rw * 0.18 + Math.sin(yy * 22 - t * 2.2 + a) * 0.03 * q;
          if (Math.abs(dx - off) < s * 0.08 * (1 - q * 0.7)) { w = Math.max(w, 0.7 - q * 0.35 + 0.15 * Math.sin(yy * 60)); k = 3; }
        }
      }
      for (let n = 0; n < 9; n++) {
        const L = s * (2.6 + hash2(n, i) * 1.4), bx = -rw * 0.9 + n * rw * 1.8 / 8;
        if (yy > 0 && yy < L) {
          const q = yy / L, off = bx * (1 - q * 0.2) + Math.sin(yy * 16 - t * 2.6 + n * 1.3) * 0.045 * q;
          if (Math.abs(dx - off) < cell * 0.55 + 0.002) { w = Math.max(w, 0.55 - q * 0.45); k = w > 0.3 ? 3 : k; }
        }
      }
    }
    return [w, k];
  },
};

// ── El recorrido: del logo a la Luna, de la Luna a la Tierra, entre las nubes hasta el atardecer y, bajo el mar, del
// arrecife al naufragio en el fondo. Cada parada es una escena por sí sola (un fondo más en Ajustes) y «recorrido» las
// encadena: cada una sube desde abajo, como el agua que se acerca, con su línea en el color de énfasis. La portada de
// la documentación hace el mismo viaje con el scroll (journeyAt).
const JOURNEY = [["translay", 0], ["luna", 0.06], ["tierra", 0.13], ["nubes", 0.21], ["atardecer", 0.28], ["mar", 0.36],
  ["arrecife", 0.46], ["ballena", 0.55], ["medusas", 0.64], ["abismo", 0.73], ["naufragio", 0.84]];
const JOURNEY_STAGE_S = 40, JOURNEY_WIPE_S = 5;  // en «recorrido», segundos en cada parada y lo que tarda en subir la siguiente
const sclamp = (x) => Math.max(0, Math.min(1, x));
// cuánto se avanzó dentro de la parada (0 al llegar, 1 al irse); null cuando la escena se ve sola
let sceneLocal = null;

// dibuja la parada i del recorrido, con la siguiente subiendo desde abajo cuando q > 0
function journeyDraw(i, local, q, u, v, t, cell, A) {
  const draw = (n, l) => { sceneLocal = l; const r = SCENES[JOURNEY[n][0]](u, v, t, cell, A); sceneLocal = null; return r; };
  if (q <= 0) return draw(i, local);
  const line = 1.04 - q * 1.12 + 0.025 * Math.sin(u * 5 + t * 0.9) + 0.012 * Math.sin(u * 13 - t * 1.3);
  if (Math.abs(v - line) < cell * 0.9) return [0.85, 1];
  return v > line ? draw((i + 1) % JOURNEY.length, 0) : draw(i, local);
}
// el recorrido según cuánto se bajó (0 a 1): la portada de la documentación lo mueve con el scroll
function journeyAt(depth, u, v, t, cell, A) {
  let i = 0;
  while (i < JOURNEY.length - 1 && depth >= JOURNEY[i + 1][1]) i++;
  const next = JOURNEY[i + 1];
  if (!next) return journeyDraw(i, sclamp((depth - JOURNEY[i][1]) / (1 - JOURNEY[i][1])), 0, u, v, t, cell, A);
  const local = sclamp((depth - JOURNEY[i][1]) / (next[1] - JOURNEY[i][1]));
  return journeyDraw(i, local, sclamp((depth - (next[1] - 0.05)) / 0.05), u, v, t, cell, A);
}

// el cielo de estrellas: pocas, quietas, que titilan; `fade` las apaga al acercarse a la Tierra
function starsAt(u, v, t, fade = 1) {
  const h = hash2(Math.floor(u * 70), Math.floor(v * 40));
  return h > 0.982 ? [(0.2 + 0.4 * (0.5 + 0.5 * Math.sin(t * 1.7 + h * 90))) * fade, h > 0.997 ? 1 : 0] : [0, 0];
}
// la Luna: disco con su lado iluminado, cráteres de borde claro y un halo fino en el color de énfasis
function moonAt(u, v, cx, cy, R) {
  const dx = u - cx, dy = v - cy, d = Math.hypot(dx, dy);
  if (d > R * 1.06) return null;
  if (d > R) return [0.55 * (1 - (d - R) / (R * 0.06)), 1];
  let w = 0.2 + sclamp(0.55 + ((dx * 0.7 - dy * 0.5) / R) * 0.55) * 0.65;
  for (const [ox, oy, cr] of [[-0.3, -0.2, 0.18], [0.25, 0.3, 0.14], [0.4, -0.35, 0.09], [-0.1, 0.45, 0.1], [-0.45, 0.25, 0.07]]) {
    const cd = Math.hypot(dx - ox * R, dy - oy * R) / (cr * R);
    if (cd < 1) w = cd > 0.78 ? Math.min(1, w + 0.2) : w * 0.62;
  }
  return [sclamp(w + 0.04 * Math.sin(u * 90) * Math.sin(v * 80)), 0];
}
// una elipse girada: < 1 adentro
function rotEll(x, y, cx, cy, rx, ry, a) {
  const dx = x - cx, dy = y - cy, c = Math.cos(a), s = Math.sin(a);
  const X = (dx * c + dy * s) / rx, Y = (-dx * s + dy * c) / ry;
  return X * X + Y * Y;
}
// los continentes, en contornos simples de longitud y latitud; se pasan una vez a un mapa de 2° por celda
const CONTINENTS = [
  [-168,66,-160,71,-140,70,-125,72,-95,72,-80,74,-62,66,-56,52,-66,45,-76,35,-81,31,-80,25,-84,30,-90,29,-97,26,-97,20,-90,21,-87,15,-83,9,-78,8,-86,12,-92,15,-105,20,-110,24,-115,30,-118,34,-124,40,-124,48,-132,55,-140,59,-152,58,-165,54,-160,60,-166,62],
  [-55,60,-44,60,-20,70,-18,80,-35,83,-60,82,-72,78,-58,75,-52,68],
  [-80,9,-72,12,-62,10,-50,0,-35,-6,-39,-14,-41,-22,-48,-26,-53,-34,-58,-38,-65,-42,-68,-52,-74,-52,-73,-42,-71,-30,-70,-18,-76,-14,-81,-5,-80,1],
  [-10,36,-9,43,-1,44,-4,48,2,51,8,54,10,58,5,62,15,69,28,71,40,67,60,69,70,73,80,73,100,77,115,74,140,72,160,70,180,68,180,65,170,60,160,55,156,51,142,53,140,46,130,42,127,35,122,30,120,22,108,20,106,10,100,13,103,1,98,8,97,17,92,22,88,22,80,15,77,8,72,20,67,24,57,26,56,24,59,22,52,16,43,13,35,28,35,33,36,36,27,37,26,40,23,36,20,40,13,45,18,40,15,38,8,44,3,43,-5,36],
  [-17,21,-17,14,-12,8,-5,5,8,4,9,-1,12,-6,13,-12,12,-18,15,-27,18,-34,26,-34,33,-28,35,-22,40,-15,40,-10,43,0,51,11,43,12,37,20,33,31,20,31,10,37,-6,36,-10,30],
  [44,-25,47,-25,50,-15,49,-12,44,-17],
  [114,-22,122,-18,130,-12,137,-12,142,-11,146,-19,153,-27,150,-37,141,-38,135,-34,129,-32,115,-35,113,-26],
  [109,1,117,7,119,-2,114,-4,110,-2], [95,5,106,-6,101,-3], [131,-1,141,-3,150,-10,141,-9,134,-4],
  [130,31,135,34,141,36,142,41,140,40,132,34], [-5,50,1,51,-2,56,-3,58,-6,57,-5,54], [-24,64,-14,64,-14,66,-22,66],
];
let landMap = null;
function isLand(lon, lat) {
  if (!landMap) {
    landMap = new Uint8Array(180 * 90);
    for (let r = 0; r < 90; r++) for (let c = 0; c < 180; c++) {
      const x = -179 + c * 2, y = 89 - r * 2;
      let inside = y < -70;  // la Antártida
      for (const P of CONTINENTS) {
        let hit = false;
        for (let i = 0, j = P.length - 2; i < P.length; j = i, i += 2) {
          if ((P[i + 1] > y) !== (P[j + 1] > y) && x < ((P[j] - P[i]) * (y - P[i + 1])) / (P[j + 1] - P[i + 1]) + P[i]) hit = !hit;
        }
        if (hit) { inside = true; break; }
      }
      landMap[r * 180 + c] = inside ? 1 : 0;
    }
  }
  const c = Math.floor((((lon + 180) % 360) + 360) % 360 / 2), r = Math.min(89, Math.max(0, Math.floor((90 - lat) / 2)));
  return landMap[r * 180 + c] === 1;
}
// agua de fondo con rayos de luz desde la superficie (más tenues cuanto más hondo)
function waterAt(u, v, t, light) {
  const ray = Math.max(0, Math.sin((u + v * 0.5) * 4 + t * 0.12)) * Math.max(0, Math.sin((u + v * 0.5) * 1.1 - t * 0.04));
  return 0.03 + 0.03 * Math.sin(u * 3 + v * 5 + t * 0.3) + ray * light * (1 - v);
}
// una tortuga marina vista desde arriba: caparazón de placas, cabeza, aletas que reman y cola
function turtleAt(u, v, cx, cy, s, t) {
  const x = (u - cx) / s, y = (v - cy) / s;
  if (Math.abs(x) > 1.6 || Math.abs(y) > 1.3) return null;
  const flap = Math.sin(t * 1.6);
  const e = x * x + (y * y) / 0.5;
  if (e < 1) {
    if (e > 0.82) return [0.8, 3];
    const seam = Math.abs(Math.sin(x * 4.5 + Math.sin(y * 5))) < 0.16 || Math.abs(Math.sin(y * 6.5)) < 0.13;
    return seam ? [0.3, 0] : [0.5 + 0.25 * (1 - e), 3];
  }
  if (Math.hypot(x - 1.03, y + 0.07) < 0.06) return [0.08, 0];  // el ojo
  if (Math.hypot(x - 1.15, y) < 0.27) return [0.62, 0];
  if (rotEll(x, y, 0.4, 0.62, 0.6, 0.16, 0.6 + flap * 0.35) < 1) return [0.55, 0];
  if (rotEll(x, y, 0.4, -0.62, 0.6, 0.16, -0.6 - flap * 0.35) < 1) return [0.5, 0];
  if (rotEll(x, y, -0.85, 0.42, 0.3, 0.12, -0.5 - flap * 0.15) < 1) return [0.45, 0];
  if (rotEll(x, y, -0.85, -0.42, 0.3, 0.12, 0.5 + flap * 0.15) < 1) return [0.45, 0];
  if (rotEll(x, y, -1.08, 0, 0.18, 0.06, 0) < 1) return [0.4, 0];
  return null;
}
// cardumen de peces chicos que cruzan (los de web/js › fishAt), en colores distintos
function smallFishAt(u, v, t, key, n, top, gap) {
  const fish = perFrame(t, key, () => Array.from({ length: n }, (_, i) => {
    const dir = i % 2 ? -1 : 1, run = (t * (0.05 + (i % 3) * 0.012) + hash2(i, 4) * 3.5) % 3.9;
    return [dir > 0 ? run - 0.35 : 3.55 - run, top + i * gap + Math.sin(t * 0.7 + i) * 0.02, 0.035 + 0.012 * (i % 3), dir];
  }));
  for (let i = 0; i < fish.length; i++) {
    const [fx, fy, fs, dir] = fish[i];
    const f = fishAt(u, v, fx, fy, fs, dir, t + i);
    if (f !== null) return [f, i % 3 === 0 ? 2 : i % 3 === 1 ? 3 : 0];
  }
  return null;
}

Object.assign(SCENES, {
  // los íconos de Translay en órbita alrededor de la Luna: elipses inclinadas, cada uno a su ritmo; detrás de la Luna
  // no se ven y de frente se ven un poco más grandes
  luna(u, v, t, cell, A = ASPECT) {
    const cx = 1.6, cy = 0.5, R = Math.min(0.34, A * 0.3), k = R / 0.34;  // en una pantalla angosta, todo a escala
    const icons = perFrame(t, "orbitas", () => TRANSLAY_ICONS.map(([, , , size], n) => {
      const rx = (0.52 + (n % 4) * 0.17) * k, ry = rx * (0.22 + (n % 3) * 0.06), tilt = ((n % 5) - 2) * 0.12;
      const a = t * (0.16 + (n % 4) * 0.03) + n * 0.53;
      const ox = Math.cos(a) * rx, oy = Math.sin(a) * ry;
      return [cx + ox * Math.cos(tilt) - oy * Math.sin(tilt), cy + ox * Math.sin(tilt) + oy * Math.cos(tilt),
        size * 0.8 * Math.max(0.7, k) * (0.82 + 0.3 * Math.sin(a)), Math.sin(a) < 0];
    }));
    const m = moonAt(u, v, cx, cy, R);
    for (let n = 0; n < icons.length; n++) {
      const [x, y, size, behind] = icons[n];
      if (behind && m) continue;  // detrás de la Luna
      const lx = (u - x) / size, ly = (v - y) / size;
      if (Math.abs(lx) > 1.25 || Math.abs(ly) > 1.25) continue;
      const f = ICON_SHAPES[TRANSLAY_ICONS[n][0]](lx, ly, (cell / size) * 0.75);
      if (f) return [f * (behind ? 0.55 : 1), TRANSLAY_ICONS[n][4] ? 1 : 3];
    }
    return m || starsAt(u, v, t);
  },

  // la Tierra que gira, con sus continentes, nubes, polos y la atmósfera en el color de énfasis; en el recorrido crece
  // hasta llenar el fondo (se baja hacia ella), sola se acerca y se aleja despacio; la Luna queda arriba, a un lado
  tierra(u, v, t, cell, A = ASPECT) {
    const p = sceneLocal ?? 0.22 + 0.18 * Math.sin(t * 0.03);
    const R = Math.min(0.36, A * 0.32) + p * p * 1.5, cx = 1.6, cy = 0.6 + p * p * 1.75;
    const dx = (u - cx) / R, dy = (v - cy) / R, d2 = dx * dx + dy * dy;
    if (d2 < 1) {
      const z = Math.sqrt(1 - d2), tilt = 0.38;
      const y = -dy * Math.cos(tilt) + z * Math.sin(tilt), zz = z * Math.cos(tilt) + dy * Math.sin(tilt);
      const lat = Math.asin(y) * 57.3, lon = Math.atan2(dx, zz) * 57.3 + t * 6 - 40;
      const light = sclamp(0.35 + 0.75 * (-dx * 0.5 - dy * 0.3 + z * 0.8));  // el sol de frente, arriba a la izquierda
      const cloud = Math.sin(lon * 0.09 + t * 0.1 + Math.sin(lat * 0.11) * 2.2) * Math.sin(lat * 0.16 + lon * 0.03) > 0.72;
      if (cloud) return [sclamp(0.2 + 0.45 * light), 0];
      if (Math.abs(lat) > 72) return [sclamp(0.25 + 0.6 * light), 0];  // el hielo de los polos
      return isLand(lon, lat) ? [sclamp(0.3 + 0.7 * light), 2] : [sclamp(0.03 + 0.09 * light), 3];
    }
    const d = Math.sqrt(d2);
    if (d < 1 + 0.025 / R) return [0.75 * (1 - ((d - 1) * R) / 0.025), 1];  // la atmósfera
    const m = moonAt(u, v, 1.6 + Math.min(A / 2 - 0.2, 1.1), 0.25 - p * 0.3, Math.min(0.14, A * 0.12) * (1 - p * 0.6));
    return m || starsAt(u, v, t, 1 - p * 0.8);
  },

  // entre las nubes: cúmulos (bultos redondos sobre una base plana, más claros arriba) en tres capas que se deslizan a
  // distinta velocidad y suben, como al ir bajando; las de adelante, más grandes y más rápidas; pasa una bandada
  nubes(u, v, t, cell, A = ASPECT) {
    const k = Math.min(1, A / 1.6), climb = sceneLocal ?? fract(t * 0.004) * 3;
    for (let L = 0; L < 3; L++) {  // de adelante hacia atrás: la primera que toca tapa a las demás
      const s = (0.4 + (2 - L) * 0.22) * k, rise = climb * (0.5 + (2 - L) * 0.45);
      for (let n = 0; n < 5; n++) {
        const span = ASPECT + 1.2;
        const cx = ((hash2(n, L * 7) * span + t * (0.012 + (2 - L) * 0.01)) % span) - 0.6;
        const y0 = 0.25 + hash2(L, n * 3) * 0.9 + L * 0.12 + (L === 2 ? 0 : 0.3) - rise;
        const cy = (((y0 + 0.3) % 1.9) + 1.9) % 1.9 - 0.1;  // las que se van por arriba vuelven por abajo
        const x = (u - cx) / s, y = (v - cy) / s;
        if (y > 0.02 || Math.abs(x) > 0.75) continue;  // la base plana
        let w = 0;
        for (let b = 0; b < 5; b++) {
          const bx = -0.48 + b * 0.24, r = 0.16 + 0.1 * Math.sin(b * 2.1 + n) + (b === 2 ? 0.08 : 0);
          const d = Math.hypot(x - bx, y + r * 0.45) / r;
          if (d < 1) w = Math.max(w, 0.35 + 0.5 * sclamp(-(y + r * 0.45) / r + 0.3) + 0.15 * (1 - d));
        }
        if (w) return [sclamp(w * 0.85 * (1 - L * 0.22)), 0];
      }
    }
    for (let b = 0; b < 5; b++) {  // la bandada: pájaros en V que aletean
      const bx = ((t * 0.03 + b * 0.07) % (ASPECT + 0.8)) - 0.4, by = 0.22 + Math.abs(b - 2) * 0.03;
      const x = (u - bx) / 0.025, y = (v - by) / 0.025, wing = Math.sin(t * 5 + b) * 0.35;
      if (Math.abs(x) < 1 && Math.abs(y - (Math.abs(x) * (0.5 + wing) - 0.3)) < 0.22) return [0.6, 1];
    }
    return [0.03 + 0.02 * Math.sin(u * 4 + t * 0.2), 0];
  },

  // arrecife de coral: corales cerebro, ramificados y abanicos de mar sobre la arena, peces de colores y una tortuga
  arrecife(u, v, t, cell, A = ASPECT) {
    let w = waterAt(u, v, t, 0.14), k = 0;
    const sand = 0.9 + 0.02 * Math.sin(u * 2.3) + 0.01 * Math.sin(u * 9);
    if (v > sand) return [0.28 + 0.18 * Math.sin(u * 40 + Math.sin(v * 30) * 2) * Math.sin(v * 60), 0];
    const ts = 0.1 * Math.min(1, 0.4 + A / 1.6);
    const vis = Math.min(A, ASPECT), left = (ASPECT - vis) / 2;  // la tortuga cruza solo lo que se ve
    const turtle = turtleAt(u, v, left - ts * 1.6 + ((t * 0.045 + 0.5) % (vis + ts * 3.2)), 0.34 + 0.03 * Math.sin(t * 0.5), ts, t);
    if (turtle) return turtle;
    const fish = smallFishAt(u, v, t, "arrecife-peces", 7, 0.46, 0.055);
    if (fish) return fish;
    for (let c = 0; c < 14; c++) {
      const bx = 0.12 + c * 0.23 + hash2(c, 9) * 0.06;
      if (Math.abs(u - bx) > 0.24) continue;  // lejos de este coral
      const base = 0.9 + 0.02 * Math.sin(bx * 2.3) + 0.01 * Math.sin(bx * 9) + 0.01;
      const kind = c % 3;
      if (kind === 0) {  // cerebro: una cúpula con surcos
        const dx = (u - bx) / 0.13, dy = (v - base) / 0.1;
        if (dy < 0 && dx * dx + dy * dy < 1) {
          const m = Math.sin(dx * 9 + Math.sin(dy * 8) * 1.6) * Math.sin(dy * 11);
          return [0.45 + (Math.abs(m) < 0.3 ? 0.35 : 0), 2];
        }
      } else if (kind === 1) {  // ramificado, con puntas claras, que se mece
        for (let b = 0; b < 5; b++) {
          const ang = -Math.PI / 2 + (b - 2) * 0.32 + Math.sin(t * 0.6 + c + b) * 0.04, len = 0.22 + 0.07 * hash2(b, c);
          const ex = bx + Math.cos(ang) * len, ey = base + Math.sin(ang) * len;
          if (Math.hypot(u - ex, v - ey) < 0.018) return [0.85, 1];
          if (segDist(u, v, bx, base, ex, ey) < 0.013) return [0.6, 1];
          const mx = bx + Math.cos(ang) * len * 0.55, my = base + Math.sin(ang) * len * 0.55, a2 = ang + (b % 2 ? 0.5 : -0.5);
          if (segDist(u, v, mx, my, mx + Math.cos(a2) * len * 0.35, my + Math.sin(a2) * len * 0.35) < 0.01) return [0.55, 1];
        }
      } else {  // abanico de mar: una red en semicírculo que ondea
        const dx = u - bx, dy = v - base, r = Math.hypot(dx, dy), R = 0.2;
        if (dy < 0 && r < R) {
          const a = Math.atan2(dy, dx) + Math.sin(t * 0.7 + c) * 0.05 * (r / R);
          if (Math.abs(Math.sin(a * 16)) < 0.25 || Math.abs(Math.sin(r * 60)) < 0.2) return [0.5 + 0.2 * (1 - r / R), 3];
          w = Math.max(w, 0.1);
        }
      }
    }
    const bub = perFrame(t, "arrecife-burbujas", () => Array.from({ length: 5 }, (_, b) =>
      [0.4 + b * 0.62 + Math.sin(t * 1.5 + b) * 0.02, 1 - fract(t * 0.07 + hash2(b, 6))]));
    for (const [bx, by] of bub) {
      const dd = Math.hypot(u - bx, v - by);
      if (dd < 0.016 && dd > 0.007) { w = Math.max(w, 0.65); k = 0; }
    }
    return [w, k];
  },

  // mar abierto: una ballena enorme que cruza despacio (surcos en el vientre, aleta que rema, cola que ondula),
  // entre plancton y rayos de luz
  ballena(u, v, t, cell, A = ASPECT) {
    let w = waterAt(u, v, t, 0.12) + v * 0.02;
    if (hash2(Math.floor(u * 80), Math.floor((v - t * 0.004) * 45)) > 0.988) return [0.35, 3];  // plancton
    // cruza solo lo que se ve (en una pantalla angosta no tarda en volver)
    const vis = Math.min(A, ASPECT), left = (ASPECT - vis) / 2;
    const L = Math.min(1, 0.35 + A * 0.4), span = vis + L * 1.25 + 0.3;
    const wx = left + vis + 0.1 - ((t * 0.035 + 0.6) % span), wy = 0.5 + 0.03 * Math.sin(t * 0.2);
    const p = (u - wx) / L;
    if (p > -0.02 && p < 1.2) {
      const y = (v - wy) / L - 0.03 * Math.sin(p * 3.5 - t * 0.9) * p * p;
      const h = p < 0.3 ? 0.13 * Math.sqrt(Math.max(0, 1 - ((0.3 - p) / 0.3) ** 2)) : 0.13 * Math.max(0, 1 - (p - 0.3) / 0.7) ** 1.3 + 0.008;
      if (p < 1 && Math.abs(y) < h) {
        if (Math.hypot(p - 0.16, y + 0.015) < 0.012) return [0.06, 0];  // el ojo
        if (p < 0.22 && Math.abs(y - 0.035) < 0.006) return [0.18, 0];  // la boca
        if (y > h * 0.25 && p < 0.55) return [Math.abs(Math.sin((y / h) * 14)) < 0.3 ? 0.75 : 0.45, 3];  // los surcos del vientre
        return [0.42 + 0.22 * (1 - Math.abs(y) / h) + 0.06 * Math.sin(p * 40) * Math.sin(y * 50), 0];
      }
      if (rotEll(p, y, 0.33, 0.17, 0.13, 0.025, 0.5 + 0.15 * Math.sin(t * 0.6)) < 1) return [0.55, 0];  // la aleta
      const q = p - 0.97;
      if (q > 0 && q < 0.2 && Math.abs(y) < q * 1.4 && Math.abs(y) > (q - 0.12) * 2.5) return [0.55, 0];  // la cola
    }
    return [w, 0];
  },

  // el abismo: casi sin luz, nieve marina que cae, chispas que se encienden y un pez linterna con su señuelo brillante
  abismo(u, v, t, cell, A = ASPECT) {
    let w = 0.015, k = 0;
    if (hash2(Math.floor(u * 90), Math.floor((v - t * 0.006) * 50)) > 0.985) w = 0.25;  // la nieve marina
    const g = hash2(Math.floor(u * 40), Math.floor(v * 25));
    if (g > 0.996) { w = 0.3 + 0.5 * Math.max(0, Math.sin(t * 1.3 + g * 50)); k = 1; }
    const s = 0.2 * Math.min(1, 0.4 + A / 1.6), reach = Math.max(0, Math.min(0.8, A / 2 - s * 1.8));
    const ax = 1.6 + Math.sin(t * 0.07) * reach, ay = 0.55 + Math.sin(t * 0.23) * 0.04, dir = Math.cos(t * 0.07) >= 0 ? 1 : -1;
    const x = ((u - ax) * dir) / s, y = (v - ay) / s;
    if (Math.abs(x) > 2.2 || Math.abs(y) > 2) return [w, k];
    const bob = Math.sin(t * 1.1) * 0.05;
    const gd = Math.hypot(x - 1, y + 1.22 + bob);
    if (gd < 0.16) return [1, 1];  // el señuelo
    if (segDist(x, y, 0.25, -0.85, 0.55, -1.4) < 0.035 || segDist(x, y, 0.55, -1.4, 0.95, -1.3 - bob) < 0.035) return [0.6, 0];
    const lit = Math.max(0, 1 - Math.hypot(x - 1, y + 1.2) / 1.6);
    const e = x * x + (y * y) / 0.8;
    if (e < 1) {
      const top = 0.12 - (0.38 * (x - 0.25)) / 0.75, bot = 0.12 + (0.38 * (x - 0.25)) / 0.75;
      if (x > 0.25 && y > top && y < bot) {  // la boca abierta, con dientes arriba y abajo
        if ((y - top < 0.14 || bot - y < 0.14) && Math.sin(x * 26) > 0) return [0.95, 0];
        return [0.03, 0];
      }
      if (Math.hypot(x - 0.45, y + 0.32) < 0.05) return [0.1, 0];
      if (Math.hypot(x - 0.45, y + 0.32) < 0.1) return [0.9, 1];  // el ojo, que refleja el señuelo
      return [0.5 + 0.15 * Math.sin(x * 12) * Math.sin(y * 10) + 0.35 * lit, 0];
    }
    if (x < -0.9 && x > -1.55 && Math.abs(y) < (-0.9 - x) * 0.9) return [0.5 + 0.2 * lit, 0];  // la cola
    if (gd < 0.75) return [Math.max(w, 0.55 * (1 - gd / 0.75) ** 2), 1];  // el halo del señuelo
    return [w, k];
  },

  // el fondo: un barco hundido sobre la arena (casco de tablas con ojos de buey, mástil roto con su vela rasgada),
  // algas, peces que pasan y burbujas que salen del casco
  naufragio(u, v, t, cell, A = ASPECT) {
    let w = 0.02 + v * 0.02, k = 0;
    if (hash2(Math.floor(u * 90), Math.floor((v - t * 0.006) * 50)) > 0.988) w = 0.22;
    const sand = 0.82 + 0.025 * Math.sin(u * 2) + 0.01 * Math.sin(u * 8);
    if (v > sand) return [0.3 + 0.2 * Math.sin(u * 40 + Math.sin(v * 30) * 2) * Math.sin(v * 60), 0];
    const fish = smallFishAt(u, v, t, "naufragio-peces", 4, 0.3, 0.09);
    if (fish) return fish;
    const S = Math.min(0.42, A * 0.42), sx = 1.6, sy = 0.71;
    const x = (u - sx) / S, y = (v - sy) / S, c = Math.cos(0.1), s = Math.sin(0.1);
    const X = x * c + y * s, Y = -x * s + y * c;
    if (Math.abs(X) < 1.1 && Y > -1.1 && Y < 0.5) {
      const hull = Math.abs(X) < 1 && Y > -0.12 && Y < -0.12 + 0.38 * Math.sqrt(Math.max(0, 1 - (X > 0 ? X * X : (X * 0.6) ** 2)));
      if (hull) {
        if (rotEll(X, Y, 0.55, 0.08, 0.14, 0.07, 0.3) < 1) return [0.04, 0];  // el boquete
        for (const px of [-0.6, -0.25, 0.1]) {
          const d = Math.hypot(X - px, Y - 0.02);
          if (d < 0.05) return [0.08, 0];
          if (d < 0.075) return [0.8, 1];
        }
        if (Y < -0.08) return [0.7, 0];  // la borda
        return [Math.abs(Math.sin(Y * 55)) < 0.2 ? 0.4 : 0.66 + 0.14 * Math.sin(X * 30) * Math.sin(Y * 20), 2];
      }
      if (X > -0.8 && X < -0.45 && Y > -0.38 && Y < -0.12) {  // la cabina
        return Math.abs(X + 0.62) < 0.05 && Math.abs(Y + 0.27) < 0.05 ? [0.08, 0] : [0.6, 2];
      }
      if (segDist(X, Y, 0.05, -0.12, 0.2, -1.0) < 0.025 || segDist(X, Y, 0.5, -0.12, 0.95, -0.4) < 0.02) return [0.75, 0];
      if (segDist(X, Y, -0.12, -0.72, 0.42, -0.8) < 0.018) return [0.7, 0];
      if (X > -0.08 && X < 0.36 && Y > -0.74 + X * -0.15 && Y < -0.45 + 0.08 * Math.sin(X * 25 + t * 0.5)) {
        return [Math.abs(Math.sin(X * 30 + t * 0.4)) < 0.3 ? 0.3 : 0.5, 3];  // la vela rasgada
      }
    }
    for (let s2 = 0; s2 < 9; s2++) {  // algas
      const [bx, len0] = KELP[s2], len = len0 * 0.6;
      if (Math.abs(u - bx) > 0.08 || Math.abs(bx - sx) < S * 1.1) continue;
      if (v > sand - len && v < sand) {
        const q = (sand - v) / len, off = Math.sin(v * 14 - t * 1.2 + s2) * 0.04 * q;
        if (Math.abs(u - bx - off) < 0.012 + 0.008 * Math.sin(v * 40 + s2)) { w = Math.max(w, 0.55 - q * 0.2); k = 2; }
      }
    }
    const bub = perFrame(t, "naufragio-burbujas", () => Array.from({ length: 4 }, (_, b) => {
      const rise = fract(t * 0.09 + b * 0.25);
      return [sx + 0.55 * S + Math.sin(t * 1.4 + b) * 0.015, sy + 0.04 * S - rise * 0.9];
    }));
    for (const [bx, by] of bub) {
      const dd = Math.hypot(u - bx, v - by);
      if (dd < 0.014 && dd > 0.006) return [0.65, 0];
    }
    return [w, k];
  },

  // el recorrido completo, solo: cada parada se queda un rato y la siguiente sube desde abajo; al final vuelve a empezar
  recorrido(u, v, t, cell, A = ASPECT) {
    const T = t % (JOURNEY.length * JOURNEY_STAGE_S), i = Math.floor(T / JOURNEY_STAGE_S), at = T - i * JOURNEY_STAGE_S;
    return journeyDraw(i, at / JOURNEY_STAGE_S, sclamp((at - (JOURNEY_STAGE_S - JOURNEY_WIPE_S)) / JOURNEY_WIPE_S), u, v, t, cell, A);
  },
});

// Dibujo de una escena. Rápido por dos cosas: los caracteres no se escriben con fillText cada vez, se copian de un
// atlas ya dibujado (cada carácter en cada color y en 10 niveles de opacidad), y solo se tocan las celdas que
// cambiaron desde el cuadro anterior (el agua cambia; la arena, la rama o una telaraña casi nunca).
// Lo usa el worker (web/js/scene-worker.js, fuera del hilo de la interfaz) y, si el navegador no lo permite, la página.
// Lo que cuesta, medido (node tools/scene_bench.js): calcular un cuadro iba de 25 a 160 ms en pantalla completa según la
// escena. Por eso: celdas más grandes en pantallas grandes (no más de ~9 000), hasta 8 cuadros por segundo y un tope de
// uso: si un cuadro tardó X ms, el siguiente espera lo necesario para no pasar del 15 % de un núcleo (en un
// equipo lento se mueve más despacio, nunca lo pone lento)
// el worker, junto a este archivo (la app lo sirve en js/; la pantalla de arranque de escritorio, en shared/js/)
// (en línea, como en la portada de la documentación, no tiene archivo: la portada dibuja sin worker)
const SCENE_WORKER = typeof document !== "undefined" && document.currentScript?.src
  ? new URL("scene-worker.js" + new URL(document.currentScript.src).search, document.currentScript.src).href  // con su ?v=
  : "js/scene-worker.js";
const SCENE_CW = 6, SCENE_FPS = 8, SCENE_MAX_CELLS = 9000, SCENE_SHARE = 0.15;
const sceneCell = (W, H) => {
  const cw = Math.max(SCENE_CW, Math.round(Math.sqrt((W * H) / (SCENE_MAX_CELLS * 1.5))));
  return [cw, Math.round(cw * 1.5)];
};

function sceneRenderer(ctx, makeCanvas) {
  const st = { W: 0, H: 0, d: 1, cw: SCENE_CW, ch: 9, cols: 0, rows: 0, prev: null, atlas: null, colors: null, fade: 1, name: "", font: "monospace" };
  const buildAtlas = () => {
    const { d, colors } = st;
    const a = makeCanvas(st.cw * d * 11, st.ch * d * 40);
    const g = a.getContext("2d");
    g.scale(d, d);
    g.font = `${st.ch - 1}px ${st.font}`;
    g.textBaseline = "top";
    for (let k = 0; k < 4; k++) {
      for (let lv = 1; lv <= 10; lv++) {
        g.globalAlpha = lv / 10;
        g.fillStyle = colors[k];
        for (let n = 1; n <= 10; n++) g.fillText(RAMP[n], n * st.cw, (k * 10 + lv - 1) * st.ch);
      }
    }
    st.atlas = a;
  };
  return {
    resize(W, H, d) {
      const [cw, ch] = sceneCell(W, H);
      Object.assign(st, { W, H, d, cw, ch, cols: Math.ceil(W / cw), rows: Math.ceil(H / ch) });
      ctx.canvas.width = Math.round(W * d);
      ctx.canvas.height = Math.round(H * d);
      st.prev = new Int16Array(st.cols * st.rows).fill(-1);
      if (st.colors) buildAtlas();
    },
    palette(colors, fade, font) {
      Object.assign(st, { colors, fade, font: font || st.font });
      if (st.W) buildAtlas();
      if (st.prev) st.prev.fill(-1);
    },
    scene(name) { st.name = name; if (st.prev) st.prev.fill(-1); },
    frame(t) {
      const field = SCENES[st.name];
      if (!field || !st.atlas || !st.cols) return;
      const { W, H, d, cols, rows, prev, atlas, fade } = st;
      const A = W / H, u0 = Math.max(0, (ASPECT - A) / 2);  // más angosta que el diseño: se recorta al centro
      const cw = st.cw * d, ch = st.ch * d;
      for (let j = 0; j < rows; j++) {
        for (let i = 0; i < cols; i++) {
          const r = field(u0 + (i / cols) * A, j / rows, t, st.cw / H, A);
          const n = Math.min(10, Math.round(r[0] * 10));
          const k = r[1] || 0;
          let key = -1, lv = 0;
          if (n >= 1) {
            const alpha = (k ? 0.35 + r[0] * 0.65 : 0.05 + r[0] * 0.75) * fade;
            lv = Math.max(1, Math.min(10, Math.round(alpha * 10)));
            key = (k * 11 + n) * 11 + lv;
          }
          const at = j * cols + i;
          if (prev[at] === key) continue;
          prev[at] = key;
          const x = i * cw, y = j * ch;
          ctx.clearRect(x, y, cw, ch);
          if (key >= 0) ctx.drawImage(atlas, n * cw, (k * 10 + lv - 1) * ch, cw, ch, x, y, cw, ch);
        }
      }
    },
  };
}

// cuándo se detiene sola (Ajustes › Apariencia › Fondo): mientras se reproduce un video y con la ventana en segundo
// plano, si esas opciones están activas (lo están por defecto); con la pestaña oculta, siempre
const sceneVideoPlaying = () => typeof vEn !== "undefined" && vEn && !vEn.paused && !vEn.ended;
const sceneShouldPause = () => {
  const p = typeof prefs !== "undefined" ? prefs : {};
  return document.hidden || (p.bg_pause_video !== false && sceneVideoPlaying()) || (p.bg_pause_blur !== false && !document.hasFocus());
};

// los colores de la escena según el tema (web/js/brand.js): tinta, protagonista, cálido y su complemento
function scenePalette() {
  const tone = themeTone();
  const p = tonePalette(tone);
  return { colors: [`rgb(${p.ink.join(",")})`, p.hot, p.warm, p.cool], fade: tone.dark ? 1 : 0.85 };
}

// dibuja una escena en un lienzo que llena `box`: en un worker si se puede (la navegación no lo siente), si no en la
// página; ~10 cuadros por segundo (las escenas son lentas), quieta con la pestaña oculta o con «reducir movimiento»
function mountScene(box, name) {
  if (!SCENES[name]) return;
  const c = document.createElement("canvas");
  c.className = "scene";
  box.append(c);
  const size = () => {
    const W = c.clientWidth, H = Math.max(box.clientHeight, 380);
    c.style.height = `${H}px`;
    return { W, H, d: window.devicePixelRatio || 1 };
  };
  let pal = scenePalette(), palKey = JSON.stringify(pal);
  const mono = "JetBrains Mono";
  if (typeof Worker !== "undefined" && c.transferControlToOffscreen) {
    const off = c.transferControlToOffscreen();
    const w = new Worker(SCENE_WORKER);
    w.postMessage({ type: "init", canvas: off, name, ...size(), ...pal, still: reduceMotion.matches }, [off]);
    const ro = new ResizeObserver(() => { const s = size(); if (s.W) w.postMessage({ type: "resize", ...s }); });
    ro.observe(c);
    ro.observe(box);
    // el tema o el color cambian: colores nuevos; la pestaña se oculta: se detiene; el lienzo sale de la página: se cierra
    let paused = false;
    const tick = setInterval(() => {
      if (!c.isConnected) { clearInterval(tick); ro.disconnect(); w.terminate(); return; }
      pal = scenePalette();
      const k = JSON.stringify(pal);
      if (k !== palKey) { palKey = k; w.postMessage({ type: "palette", ...pal }); }
      // quieta con la pestaña oculta y, según Ajustes, mientras se reproduce un video o con la ventana en segundo plano
      const stop = sceneShouldPause();
      if (stop !== paused) { paused = stop; w.postMessage({ type: "pause", paused }); }
    }, 500);
    return;
  }
  // sin worker: lo mismo en la página
  const r = sceneRenderer(c.getContext("2d"), (w, h) => Object.assign(document.createElement("canvas"), { width: w, height: h }));
  r.scene(name);
  r.palette(pal.colors, pal.fade, mono);
  const fit = () => { const s = size(); if (s.W) r.resize(s.W, s.H, s.d); };
  new ResizeObserver(fit).observe(c);
  new ResizeObserver(fit).observe(box);
  let last = -1, wait = 1 / SCENE_FPS;
  const draw = (t) => {
    if ((last >= 0 && t - last < wait) || sceneShouldPause()) return;
    last = t;
    const p = scenePalette(), k = JSON.stringify(p);
    if (k !== palKey) { palKey = k; r.palette(p.colors, p.fade); }
    const a = performance.now();
    r.frame(t);
    const took = (performance.now() - a) / 1000;
    wait = Math.max(1 / SCENE_FPS, took / SCENE_SHARE);  // el mismo tope de uso que en el worker
  };
  requestAnimationFrame(() => { fit(); brandLoop(draw, () => c.isConnected); });
}

// el fondo de toda la app: una capa fija detrás de todo (z-index -1: encima del fondo de la página y debajo
// del contenido), la misma en el inicio, la biblioteca, Ajustes y el video. Se rearma solo si cambia la escena.
function syncSceneBg() {
  const mode = typeof homeBgMode === "function" ? homeBgMode() : "translay";
  let layer = document.getElementById("scene-layer");
  if (!SCENES[mode]) { layer?.remove(); return; }
  if (layer?.dataset.scene === mode) return;
  layer?.remove();
  layer = el("div", { id: "scene-layer", "aria-hidden": "true", "data-scene": mode });
  document.body.prepend(layer);
  mountScene(layer, mode);
}
