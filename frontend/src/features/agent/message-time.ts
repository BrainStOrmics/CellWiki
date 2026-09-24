/**
 * 消息时间戳的显示口径：今天只给 HH:MM，同年补月日，跨年才带年份。
 * 库里存的是 UTC，这里一律按本机时区渲染（用户问的是"我几点问的"）。
 */

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function localClock(date: Date): string {
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function formatMessageTime(iso: string | undefined, now: Date = new Date()): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  const sameDay =
    date.getFullYear() === now.getFullYear()
    && date.getMonth() === now.getMonth()
    && date.getDate() === now.getDate();
  if (sameDay) return localClock(date);
  const day = `${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  return date.getFullYear() === now.getFullYear()
    ? `${day} ${localClock(date)}`
    : `${date.getFullYear()}-${day} ${localClock(date)}`;
}

/** 悬停时给的完整时间，省得在"今天/今年"的口径里猜年份。 */
export function formatMessageTimeFull(iso: string | undefined): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${localClock(date)}`;
}
