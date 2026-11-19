/** Tokens from "Design System from Akshat Dani" (colours, fonts, radius, motion). */
export default {
  content: ["./index.html", "./client.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#14151A",
        panel: { DEFAULT: "#1E2027", raised: "#262932" },
        hairline: "#2A2D36",
        ivory: { DEFAULT: "#F2EEE6", 70: "rgba(242,238,230,0.70)", 35: "rgba(242,238,230,0.35)" },
        gold: { DEFAULT: "#C9A84C", light: "#F0D98A", deep: "#8F7635" },
        teal: { DEFAULT: "#2ED3B7", ink: "#0E2B26" },
        alert: "#E0533D",
        paper: "#FAF8F3",
        ink: "#14151A",
      },
      fontFamily: {
        sans: ["Manrope Variable", "Manrope", "Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      borderRadius: { card: "14px", frame: "18px", input: "12px" },
      letterSpacing: { kicker: "0.18em", wordmark: "0.26em" },
      transitionTimingFunction: { enter: "cubic-bezier(0.2,0.8,0.2,1)", state: "cubic-bezier(0.4,0,0.2,1)" },
      boxShadow: { float: "0 40px 90px rgba(0,0,0,0.6)", gold: "0 0 40px rgba(201,168,76,0.25)", teal: "0 0 60px rgba(46,211,183,0.10)" },
    },
  },
  plugins: [],
};
