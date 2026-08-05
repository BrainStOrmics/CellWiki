import { describe, expect, it } from "vitest";
import { resolveInitialPageId } from "./AppShell";

describe("initial Wiki page selection", () => {
  it("restores the persisted composer page when it still exists", () => {
    const pages = [
      { page_id: "activated_cd4_t_cell" },
      { page_id: "bone_marrow_derived_macrophage" },
    ];

    expect(resolveInitialPageId(pages, { page_id: "bone_marrow_derived_macrophage" })).toBe(
      "bone_marrow_derived_macrophage",
    );
  });
});
