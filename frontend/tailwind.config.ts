import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#080c18",
        surface: "#0e1425",
        surface2: "#151e36",
        border: "#1e2d54",
        "border-bright": "#2e4480",
      },
      boxShadow: {
        node: "0 4px 24px 0 rgba(99,102,241,0.15)",
        "node-selected": "0 0 0 2px rgba(139,92,246,0.7), 0 4px 24px 0 rgba(99,102,241,0.25)",
      },
    },
  },
  plugins: [],
} satisfies Config;
