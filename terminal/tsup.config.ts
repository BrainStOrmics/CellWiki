import { defineConfig } from "tsup";

export default defineConfig({
  entry: ["src/cli.tsx"],
  format: ["esm"],
  target: "node22",
  outDir: "dist",
  clean: true,
  splitting: false,
  sourcemap: true,
  external: ["ink", "react", "react/jsx-runtime"],
  banner: { js: "#!/usr/bin/env node" },
});
