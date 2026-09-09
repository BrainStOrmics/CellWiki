import { expect, test, type Page } from "@playwright/test";

/**
 * Guards the two-theme contract: light mode must not contain dark surfaces and
 * dark mode must not contain light surfaces. Intentionally small allowlist keeps
 * status dots and accent-filled primary buttons from failing the scan.
 */

async function themeViolations(page: Page) {
  return page.evaluate(() => {
    // Controls cross-fade background-color over 120ms, so scanning right after a
    // theme switch reads the fade's starting colour. Freeze motion to measure the
    // settled surface, which is what this contract is about.
    if (!document.getElementById("theme-scan-freeze")) {
      const freeze = document.createElement("style");
      freeze.id = "theme-scan-freeze";
      freeze.textContent = "*, *::before, *::after { transition: none !important; animation: none !important; }";
      document.head.append(freeze);
    }
    const allowedClassPart = /source-state|rail-health|connection|compose-tool-button|settings-save|approve-action|primary-action|theme-toggle/;
    const luminance = ([r, g, b]: number[]) => {
      const f = (v: number) => {
        const c = v / 255;
        return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
      };
      return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
    };
    const isDark = document.documentElement.dataset.theme === "dark";
    const violations: string[] = [];
    for (const el of document.querySelectorAll<HTMLElement>("body *")) {
      const rect = el.getBoundingClientRect();
      if (rect.width < 12 || rect.height < 12) continue;
      const tag = el.tagName.toLowerCase();
      if (["svg", "path", "circle", "line", "polygon"].includes(tag)) continue;
      const cls = typeof el.className === "string" ? el.className : "";
      if ((cls && allowedClassPart.test(cls)) || el.closest(".compose-actions")) continue;
      let node: HTMLElement | null = el;
      let bg: number[] | null = null;
      while (node) {
        const match = getComputedStyle(node).backgroundColor.match(/rgba?\(([^)]+)\)/);
        if (match) {
          const parts = match[1].split(",").map((s) => parseFloat(s.trim()));
          const alpha = parts.length > 3 ? parts[3] : 1;
          if (alpha >= 0.9) {
            bg = [parts[0], parts[1], parts[2]];
            break;
          }
        }
        node = node.parentElement;
      }
      if (!bg) continue;
      const lum = luminance(bg);
      if (isDark && lum > 0.75) {
        violations.push(`${tag}.${cls} bg=rgb(${bg.join(",")}) lum=${lum.toFixed(3)}`);
      }
      if (!isDark && lum < 0.4) {
        violations.push(`${tag}.${cls} bg=rgb(${bg.join(",")}) lum=${lum.toFixed(3)}`);
      }
    }
    return violations;
  });
}

test("light and dark themes stay surface-consistent on the wiki workbench", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/", { waitUntil: "domcontentloaded", timeout: 120_000 });
  await expect(page.getByText("CellWiki", { exact: true }).first()).toBeVisible();
  await expect(page.locator(".reader-scroll")).not.toBeEmpty();

  await expect.poll(() => page.locator("html").getAttribute("data-theme")).toBe("light");
  expect(await themeViolations(page), "light theme leaked dark surfaces").toEqual([]);

  await page.getByRole("button", { name: /切换到深色模式|Switch to dark mode/ }).click();
  await expect.poll(() => page.locator("html").getAttribute("data-theme")).toBe("dark");
  expect(await themeViolations(page), "dark theme leaked light surfaces").toEqual([]);
});
