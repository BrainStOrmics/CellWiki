import { describe, expect, it } from "vitest";
import { formatMessageTime, formatMessageTimeFull } from "./message-time";

describe("formatMessageTime", () => {
  // 固定"现在"，断言才不随运行日期漂移（日期一律按本机时区构造，跨时区也成立）
  const now = new Date(2026, 8, 23, 20, 0, 0);

  it("当天只给时分", () => {
    expect(formatMessageTime(new Date(2026, 8, 23, 14, 32, 0).toISOString(), now)).toBe("14:32");
    expect(formatMessageTime(new Date(2026, 8, 23, 9, 5, 0).toISOString(), now)).toBe("09:05");
  });

  it("同年补月日，跨年才带年份", () => {
    expect(formatMessageTime(new Date(2026, 8, 22, 9, 5, 0).toISOString(), now)).toBe("09-22 09:05");
    expect(formatMessageTime(new Date(2025, 11, 3, 8, 0, 0).toISOString(), now)).toBe("2025-12-03 08:00");
  });

  it("没有时间或时间非法时不出读数", () => {
    expect(formatMessageTime(undefined, now)).toBeNull();
    expect(formatMessageTime("", now)).toBeNull();
    expect(formatMessageTime("not-a-date", now)).toBeNull();
  });

  it("悬停用完整时间，始终带年份", () => {
    const iso = new Date(2026, 8, 23, 14, 32, 0).toISOString();
    expect(formatMessageTimeFull(iso)).toBe("2026-09-23 14:32");
    expect(formatMessageTimeFull(undefined)).toBeNull();
  });
});
