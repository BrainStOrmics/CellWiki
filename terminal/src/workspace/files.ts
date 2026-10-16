import { readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

const SKIP_DIRECTORIES = new Set([
  ".git",
  ".venv",
  "node_modules",
  "data",
  "cache",
  "output",
  "dist",
  "coverage",
]);

export function listWorkspaceFiles(
  root: string,
  options: { limit?: number; maxDepth?: number } = {},
): string[] {
  const limit = options.limit ?? 2_000;
  const maxDepth = options.maxDepth ?? 6;
  const files: string[] = [];

  const walk = (directory: string, depth: number): void => {
    if (files.length >= limit || depth > maxDepth) {
      return;
    }
    let entries: string[];
    try {
      entries = readdirSync(directory);
    } catch {
      return;
    }
    for (const entry of entries) {
      if (files.length >= limit) {
        return;
      }
      const fullPath = join(directory, entry);
      let stats;
      try {
        stats = statSync(fullPath);
      } catch {
        continue;
      }
      if (stats.isDirectory()) {
        if (SKIP_DIRECTORIES.has(entry)) {
          continue;
        }
        walk(fullPath, depth + 1);
      } else if (stats.isFile()) {
        files.push(relative(root, fullPath).split(sep).join("/"));
      }
    }
  };

  walk(root, 0);
  return files.sort();
}
