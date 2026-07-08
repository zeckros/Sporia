// tailwind.config.js — thème repris de l'ancien <script>tailwind.config</script> d'index.html.
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./web/index.html", "./web/js/**/*.js"],
  theme: {
    extend: {
      fontFamily: { sans: ["Inter", "system-ui", "sans-serif"] },
      colors: { brand: { 50: "#fdf3e7", 100: "#fbe2c4", 500: "#c2620e", 600: "#9a4c0b", 700: "#7c3d09" } },
      boxShadow: {
        soft: "0 2px 14px rgba(15,23,42,.06)",
        card: "0 8px 28px rgba(15,23,42,.10)",
        lg2: "0 24px 70px rgba(15,23,42,.22)",
      },
    },
  },
  plugins: [],
};
