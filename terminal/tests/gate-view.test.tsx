import { render } from "ink-testing-library";
import { describe, expect, it } from "vitest";

import { GateView } from "../src/components/GateView";
import { findTheme } from "../src/theme/themes";

describe("GateView", () => {
  it("orders content before scaffold in the file summary and preview", () => {
    const patch = [
      "diff --git a/.gitignore b/.gitignore",
      "--- a/.gitignore",
      "+++ b/.gitignore",
      "@@ -0,0 +1 @@",
      "+data/runtime/",
      "diff --git a/wiki/cell_types/alpha.md b/wiki/cell_types/alpha.md",
      "--- a/wiki/cell_types/alpha.md",
      "+++ b/wiki/cell_types/alpha.md",
      "@@ -0,0 +1 @@",
      "+# Alpha Cell",
      "",
    ].join("\n");
    const { lastFrame, unmount } = render(
      <GateView
        gate={{ kind: "diff", runId: "run_1", diffId: "diff_1", patch }}
        width={100}
        previewLines={8}
        theme={findTheme("dark")}
      />,
    );

    const frame = lastFrame() ?? "";
    expect(frame).toContain(
      "files: wiki/cell_types/alpha.md, .gitignore · scaffold 1 file hidden from preview",
    );
    expect(frame).toContain("+# Alpha Cell");
    expect(frame).not.toContain("+data/runtime/");
    unmount();
  });
});
