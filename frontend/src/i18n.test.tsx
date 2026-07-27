import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LanguageProvider, useI18n } from "./i18n";

vi.mock("./runtime", () => ({
  productFetch: vi.fn().mockResolvedValue({ ok: false }),
}));

function LanguageProbe() {
  const { language, setLanguage, t } = useI18n();
  return (
    <button onClick={() => setLanguage(language === "zh-CN" ? "en" : "zh-CN")}>
      {t("search.title")}
    </button>
  );
}

describe("application language", () => {
  it("defaults to Chinese and can switch the whole provider to English", () => {
    render(<LanguageProvider><LanguageProbe /></LanguageProvider>);

    expect(screen.getByRole("button", { name: "全局搜索" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "全局搜索" }));
    expect(screen.getByRole("button", { name: "Global search" })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("en");
  });
});
