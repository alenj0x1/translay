// @ts-check
import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";
import starlightLinksValidator from "starlight-links-validator";

// On GitHub Pages: SITE=https://<user>.github.io BASE=/<repo> (see .github/workflows/docs.yml)
export default defineConfig({
  site: process.env.SITE || "http://localhost:4321",
  base: process.env.BASE || "/",
  devToolbar: { enabled: false }, // Astro's toolbar flashed on every page
  integrations: [
    starlight({
      title: "Translay",
      description: "Translate and dub videos from English to Spanish with each speaker's voice, on your own computer.",
      logo: { src: "./src/assets/mark.svg", alt: "" },
      favicon: "/favicon.svg",
      defaultLocale: "root",
      locales: {
        root: { label: "English", lang: "en" },
        es: { label: "Español", lang: "es" },
      },
      customCss: [
        "@fontsource/plus-jakarta-sans/400.css",
        "@fontsource/plus-jakarta-sans/500.css",
        "@fontsource/plus-jakarta-sans/600.css",
        "@fontsource/plus-jakarta-sans/700.css",
        "@fontsource/plus-jakarta-sans/800.css",
        "./src/styles/translay.css",
      ],
      plugins: [starlightLinksValidator({ errorOnRelativeLinks: false })],
      social: [{ icon: "github", label: "GitHub", href: "https://github.com/alenj0x1/translay" }],
      editLink: { baseUrl: "https://github.com/alenj0x1/translay/edit/main/docs/" },
      lastUpdated: true,
      pagination: true,
      sidebar: [
        {
          label: "Getting started",
          translations: { es: "Empezar" },
          items: ["getting-started/install", "getting-started/first-video", "getting-started/from-source", "getting-started/docker"],
        },
        { label: "Guide", translations: { es: "Guía de uso" }, items: [{ autogenerate: { directory: "guide" } }] },
        {
          label: "Access and integrations",
          translations: { es: "Acceso e integraciones" },
          items: ["integrations/access", "integrations/api", "integrations/webhooks"],
        },
        { label: "How it works", translations: { es: "Cómo funciona" }, items: [{ autogenerate: { directory: "how-it-works" } }] },
        { label: "Reference", translations: { es: "Referencia" }, items: [{ autogenerate: { directory: "reference" } }] },
        { label: "Development", translations: { es: "Desarrollo" }, items: [{ autogenerate: { directory: "development" } }] },
        { label: "Changelog", translations: { es: "Cambios" }, slug: "changelog" },
        {
          label: "Releases on GitHub",
          translations: { es: "Versiones en GitHub" },
          link: "https://github.com/alenj0x1/translay/releases",
          attrs: { target: "_blank" },
        },
      ],
    }),
  ],
});
