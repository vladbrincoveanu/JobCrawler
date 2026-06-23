import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        status: {
          success: "rgb(34 197 94)",
          failed: "rgb(239 68 68)",
          partial: "rgb(234 179 8)",
          running: "rgb(59 130 246)",
          dry_run: "rgb(107 114 128)",
        },
      },
    },
  },
  plugins: [],
};

export default config;
