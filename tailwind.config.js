// tailwind.config.js — thème repris de l'ancien <script>tailwind.config</script> d'index.html.
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/sporia/web/templates/**/*.html", "./web/js/**/*.js"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        display: ["Clash Display", "Archivo Black", "system-ui", "sans-serif"],
        serif: ["Fraunces", "Iowan Old Style", "Georgia", "serif"],
        mono: ["Space Mono", "ui-monospace", "monospace"],
      },
      colors: {
        brand: { 50: "#fdf3e7", 100: "#fbe2c4", 500: "#c2620e", 600: "#9a4c0b", 700: "#7c3d09" },
        sousbois: "#191510",
        os: "#efe6d3",
        girolle: "#f2a93b",
        cepe: "#b9793f",
        lactaire: "#d9772e",
        mycene: "#c6f24e",
      },
      boxShadow: {
        soft: "0 2px 14px rgba(15,23,42,.06)",
        card: "0 8px 28px rgba(15,23,42,.10)",
        lg2: "0 24px 70px rgba(15,23,42,.22)",
      },
    },
  },
  plugins: [],
};
