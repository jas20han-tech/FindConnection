import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        obsidian: "#07090E",
        panel: "#0A0E17",
        edge: "#1E293B",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      boxShadow: {
        glass: "0 20px 45px -20px rgba(0,0,0,0.85)",
        neon: "0 0 24px -4px rgba(56,189,248,0.45)",
      },
      animation: {
        "pulse-slow": "pulseSlow 3s ease-in-out infinite",
        "fade-in": "fadeIn 0.35s ease-out both",
        "slide-up": "slideUp 0.35s cubic-bezier(0.22,1,0.36,1) both",
        shimmer: "shimmer 2.4s linear infinite",
      },
      keyframes: {
        pulseSlow: {
          "0%, 100%": { opacity: "0.6" },
          "50%": { opacity: "1" },
        },
        fadeIn: { from: { opacity: "0" }, to: { opacity: "1" } },
        slideUp: {
          from: { opacity: "0", transform: "translateY(10px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          from: { backgroundPosition: "200% 0" },
          to: { backgroundPosition: "-200% 0" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
