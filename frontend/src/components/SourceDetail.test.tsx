import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(cleanup);
import { LanguageProvider } from "../i18n";
import type { Source } from "../types";
import { SourceDetail } from "./SourceDetail";
import { productFetch } from "../runtime";

vi.mock("../runtime", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../runtime")>();
  return {
    ...actual,
    productFetch: vi.fn(),
  };
});

const source: Source = {
  source_id: "source-paper",
  source_type: "pdf",
  original_name: "paper.pdf",
  status: "ready",
  content_hash: "0123456789abcdef0123456789abcdef",
};

function renderDetail(overrides: Partial<Parameters<typeof SourceDetail>[0]> = {}) {
  return render(
    <LanguageProvider>
      <SourceDetail
        source={source}
        onDelete={vi.fn()}
        {...overrides}
      />
    </LanguageProvider>,
  );
}

describe("SourceDetail", () => {
  it("renders a PDF source inline without fetching its bytes", () => {
    const { container } = renderDetail();

    const frame = container.querySelector("iframe") as HTMLIFrameElement;
    expect(frame).not.toBeNull();
    expect(frame.src).toContain("/api/sources/source-paper/file");
    expect(productFetch).not.toHaveBeenCalledWith(expect.stringContaining("/api/sources/source-paper/file"));
  });

  it("keeps long source names inspectable when the header is visually clamped", () => {
    const longName = "ENCSR659HPI.research.with.a.very.long.registered-source-name.json";

    renderDetail({ source: { ...source, original_name: longName } });

    const title = screen.getByRole("heading", { name: longName });
    expect(title).toHaveClass("source-review-title");
    expect(title).toHaveAttribute("title", longName);
  });

  it("requests confirmation through the delete action", () => {
    const onDelete = vi.fn();
    renderDetail({ onDelete });

    fireEvent.click(screen.getByTestId("delete-source"));
    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it("renders Markdown sources through the existing reader", async () => {
    vi.mocked(productFetch).mockResolvedValue({
      ok: true,
      text: async () => "# Provenance Title",
    } as Response);

    renderDetail({ source: { ...source, source_type: "markdown", original_name: "notes.md" } });

    expect(await screen.findByRole("heading", { name: "Provenance Title" })).toBeInTheDocument();
    expect(productFetch).toHaveBeenCalledWith(expect.stringContaining("/api/sources/source-paper/file"));
  });
});
