const USD_INR = Number(process.env.NEXT_PUBLIC_USD_INR) || 88;

export function formatUsd(value: number): string {
  return `$${value.toFixed(value < 0.01 ? 4 : 3)}`;
}

export function formatInr(usd: number): string {
  return `≈ ₹${(usd * USD_INR).toFixed(2)}`;
}

export function formatNumber(n: number): string {
  return n.toLocaleString("en-US");
}

/** "7 Nov 2026, 11:30 UTC" */
export function formatUtc(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const text = d.toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  });
  return `${text} UTC`;
}

/** The viewer's local time with zone name, e.g. "7 Nov 2026, 17:00 IST". */
export function formatLocal(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

/** Value for <input type="datetime-local"> (local time, no zone). */
export function toLocalInputValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
