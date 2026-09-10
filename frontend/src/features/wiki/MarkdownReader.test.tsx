import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LanguageProvider } from "../../i18n";
import { MarkdownReader, leadingHeading, sameHeadingText, wikiTargetFor } from "./MarkdownReader";

vi.mock("../../runtime", () => ({
  productFetch: vi.fn().mockResolvedValue({ ok: false }),
}));

describe("MarkdownReader", () => {
  it("renders GFM tables and controlled Wiki links", () => {
    const openWikiPage = vi.fn();
    render(
      <LanguageProvider>
        <MarkdownReader
          markdown={"# Marker table\n\n| Marker | State |\n| --- | --- |\n| CD3D | positive |\n\n[[T cell|Open T cell]]"}
          onWikiLink={openWikiPage}
        />
      </LanguageProvider>,
    );

    expect(screen.getByRole("table")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open T cell" }));
    expect(openWikiPage).toHaveBeenCalledWith("T cell");
  });

  it("drops a leading H1 that repeats the page title", () => {
    const { container } = render(
      <LanguageProvider>
        <MarkdownReader title="B Cell" markdown={"# B Cell\n\nB lymphocytes."} />
      </LanguageProvider>,
    );

    expect(container.querySelector("h1")).toBeNull();
    expect(screen.getByText("B lymphocytes.")).toBeInTheDocument();
  });

  it("reports the leading heading so the shell can skip its own title", () => {
    expect(leadingHeading("# B Cell\n\nB lymphocytes.")).toBe("B Cell");
    expect(leadingHeading("> Quote\n\n# Later heading")).toBeNull();
    expect(sameHeadingText("CellWiki Audit Report", "audit_report")).toBe(false);
    expect(sameHeadingText("B Cell", "b cell ")).toBe(true);
  });

  it("keeps a leading H1 that differs from the page title", () => {
    render(
      <LanguageProvider>
        <MarkdownReader title="audit_report" markdown={"# CellWiki Audit Report\n\nTotal issues: 1"} />
      </LanguageProvider>,
    );

    expect(screen.getByRole("heading", { name: "CellWiki Audit Report", level: 1 })).toBeInTheDocument();
  });

  it("keeps relative page links inside the reader", () => {
    const openWikiPage = vi.fn();
    render(
      <LanguageProvider>
        <MarkdownReader markdown={"Parent: [lymphoid cell](lymphoid_cell.md)"} onWikiLink={openWikiPage} />
      </LanguageProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "lymphoid cell" }));
    expect(openWikiPage).toHaveBeenCalledWith("lymphoid_cell");
  });

  it("classifies navigation targets", () => {
    expect(wikiTargetFor("/wiki/T%20cell")).toBe("T cell");
    expect(wikiTargetFor("lymphoid_cell.md")).toBe("lymphoid_cell");
    expect(wikiTargetFor("./regulatory_t_cell.md#markers")).toBe("regulatory_t_cell");
    expect(wikiTargetFor("https://doi.org/10.1000/x")).toBeNull();
    expect(wikiTargetFor("#user-content-fn-paper")).toBeNull();
    expect(wikiTargetFor("")).toBeNull();
  });

  it("sanitizes executable HTML", () => {
    const { container } = render(
      <LanguageProvider>
        <MarkdownReader markdown={'<script>alert("unsafe")</script>\n\nSafe text'} />
      </LanguageProvider>,
    );

    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText("Safe text")).toBeInTheDocument();
  });

  it("renders footnotes with a navigable reference", () => {
    render(
      <LanguageProvider>
        <MarkdownReader markdown={"Evidence-backed statement.[^paper]\n\n[^paper]: Primary paper."} />
      </LanguageProvider>,
    );

    expect(screen.getByText("Primary paper.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /1/ })).toHaveAttribute("href", "#user-content-fn-paper");
  });
});
