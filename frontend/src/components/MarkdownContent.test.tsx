import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarkdownContent } from "./MarkdownContent";

describe("MarkdownContent", () => {
  it("renders GFM headings, lists, tables, and fenced code", () => {
    const { container } = render(
      <MarkdownContent
        content={'## Conclusion\n\n- FOXP3\n- IL2RA\n\n| Marker | Role |\n| --- | --- |\n| FOXP3 | Treg |\n\n```python\nprint("evidence")\n```'}
      />,
    );

    expect(container.querySelector("h2")?.textContent).toBe("Conclusion");
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(container.querySelector("table")).not.toBeNull();
    expect(container.querySelector("pre code")?.textContent).toContain("evidence");
  });

  it("does not interpret raw HTML as application markup", () => {
    const { container } = render(<MarkdownContent content={'<script>alert("unsafe")</script>\n\nPlain text'} />);

    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain("Plain text");
  });
});
