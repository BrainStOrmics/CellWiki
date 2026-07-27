import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { useUiStore } from "../stores/ui-store";

function systemPrefersDark(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

/** Apply the OS theme by default and keep manual theme changes session-only. */
export function ThemeToggle({ lightLabel, darkLabel }: { lightLabel: string; darkLabel: string }) {
  const themeOverride = useUiStore((state) => state.themeOverride);
  const setThemeOverride = useUiStore((state) => state.setThemeOverride);
  const [systemDark, setSystemDark] = useState(systemPrefersDark);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    setSystemDark(media.matches);
    if (themeOverride) return;
    const handleChange = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    media.addEventListener?.("change", handleChange);
    return () => media.removeEventListener?.("change", handleChange);
  }, [themeOverride]);

  const isDark = themeOverride ? themeOverride === "dark" : systemDark;

  useEffect(() => {
    document.documentElement.dataset.theme = isDark ? "dark" : "light";
    document.documentElement.style.colorScheme = isDark ? "dark" : "light";
  }, [isDark]);

  const nextTheme = isDark ? "light" : "dark";
  const label = isDark ? lightLabel : darkLabel;
  return (
    <button
      className="theme-toggle"
      type="button"
      onClick={() => setThemeOverride(nextTheme)}
      title={label}
      aria-label={label}
    >
      {isDark ? <Sun size={14} /> : <Moon size={14} />}
    </button>
  );
}
