/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#FFFFFF",
        canvas: "#F7F7F5",
        ink: "#1A1D21",
        muted: "#5C6470",
        line: "#E4E4E1",
        focus: "#2563EB",
        danger: "#DC2626",
        hover: "#FAFAF9",
        pill: "#EFEFED",
        status: {
          // text colors
          saved: "#475569",
          applied: "#1D4ED8",
          assessment: "#6D28D9",
          interview: "#B45309",
          offer: "#047857",
          rejected: "#B91C1C",
          ghosted: "#52525B",
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
        // The only shadow in the system: dialogs and popovers.
        pop: "0 1px 2px rgba(26,29,33,0.06), 0 8px 24px rgba(26,29,33,0.12)",
        drag: "0 2px 6px rgba(26,29,33,0.10), 0 10px 24px rgba(26,29,33,0.14)",
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
