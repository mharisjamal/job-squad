/** @type {import('tailwindcss').Config} */

// Every color token resolves to a CSS variable defined in src/index.css.
// The rgb(var(--x) / <alpha-value>) form keeps Tailwind opacity modifiers
// (bg-ink/60, text-muted/80) working. No component may hardcode a hex.
const token = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: token("canvas"),
        paper: token("paper"),
        raised: token("raised"),
        hover: token("hover"),
        line: token("line"),
        "line-strong": token("line-strong"),
        ink: token("ink"),
        "ink-hover": token("ink-hover"),
        muted: token("muted"),
        focus: token("focus"),
        danger: token("danger"),
        scrim: token("scrim"),
        status: {
          "saved-text": token("status-saved-text"),
          "saved-bg": token("status-saved-bg"),
          "saved-dot": token("status-saved-dot"),
          "applied-text": token("status-applied-text"),
          "applied-bg": token("status-applied-bg"),
          "applied-dot": token("status-applied-dot"),
          "assessment-text": token("status-assessment-text"),
          "assessment-bg": token("status-assessment-bg"),
          "assessment-dot": token("status-assessment-dot"),
          "interview-text": token("status-interview-text"),
          "interview-bg": token("status-interview-bg"),
          "interview-dot": token("status-interview-dot"),
          "offer-text": token("status-offer-text"),
          "offer-bg": token("status-offer-bg"),
          "offer-dot": token("status-offer-dot"),
          "rejected-text": token("status-rejected-text"),
          "rejected-bg": token("status-rejected-bg"),
          "rejected-dot": token("status-rejected-dot"),
          "ghosted-text": token("status-ghosted-text"),
          "ghosted-bg": token("status-ghosted-bg"),
          "ghosted-dot": token("status-ghosted-dot"),
        },
      },
      fontFamily: {
        sans: ["'IBM Plex Sans'", "system-ui", "sans-serif"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "monospace"],
      },
      borderRadius: {
        md: "6px",
        lg: "10px",
      },
      boxShadow: {
        // Elevation is a surface lightness step; dialogs keep one subtle shadow.
        pop: "0 1px 2px rgb(0 0 0 / 0.16), 0 8px 24px rgb(0 0 0 / 0.24)",
        drag: "0 2px 6px rgb(0 0 0 / 0.20), 0 10px 24px rgb(0 0 0 / 0.28)",
      },
      fontSize: {
        small: ["12.5px", { lineHeight: "1.45" }],
      },
      transitionDuration: {
        DEFAULT: "140ms",
      },
    },
  },
  plugins: [],
};
