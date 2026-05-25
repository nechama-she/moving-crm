import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
  },
  build: {
    outDir: "dist",
  },
  base: process.env.NODE_ENV === "production" ? "/dispatch/" : "/",
});
