// @ts-check
import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";

// En GitHub Pages: SITE=https://<usuario>.github.io BASE=/<repo> (ver .github/workflows/docs.yml)
export default defineConfig({
  site: process.env.SITE || "http://localhost:4321",
  base: process.env.BASE || "/",
  integrations: [
    starlight({
      title: "Translay",
      description: "Traduce y dobla videos del inglés al español con la voz de cada persona, en tu propio equipo.",
      logo: { src: "./src/assets/mark.svg", alt: "" },
      favicon: "/favicon.svg",
      defaultLocale: "root",
      locales: { root: { label: "Español", lang: "es" } },
      customCss: ["./src/styles/translay.css"],
      head: [
        { tag: "link", attrs: { rel: "preconnect", href: "https://fonts.googleapis.com" } },
        { tag: "link", attrs: { rel: "preconnect", href: "https://fonts.gstatic.com", crossorigin: "" } },
        { tag: "link", attrs: { rel: "stylesheet", href: "https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" } },
      ],
      lastUpdated: true,
      pagination: true,
      sidebar: [
        { label: "Empezar", items: ["empezar/instalacion", "empezar/docker", "empezar/primer-video"] },
        { label: "Guía de uso", items: [{ autogenerate: { directory: "guia" } }] },
        { label: "Acceso e integraciones", items: ["integraciones/acceso", "integraciones/api", "integraciones/webhooks"] },
        { label: "Cómo funciona", items: [{ autogenerate: { directory: "funcionamiento" } }] },
        { label: "Referencia", items: [{ autogenerate: { directory: "referencia" } }] },
        { label: "Desarrollo", items: [{ autogenerate: { directory: "desarrollo" } }] },
        { label: "Cambios", link: "/cambios/" },
      ],
    }),
  ],
});
