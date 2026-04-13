export interface PendingOutboxItem {
  local_id: number;
  room_id: number;
  text: string;
  created_at: string;
  attempts: number;
}

export function loadPendingOutbox(storageKey: string): PendingOutboxItem[] {
  try {
    const raw = localStorage.getItem(storageKey);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as PendingOutboxItem[];
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (item) =>
        item &&
        Number.isFinite(Number(item.local_id)) &&
        Number.isFinite(Number(item.room_id)) &&
        typeof item.text === 'string' &&
        item.text.trim().length > 0
    );
  } catch {
    return [];
  }
}

export function savePendingOutbox(storageKey: string, items: PendingOutboxItem[]): void {
  try {
    localStorage.setItem(storageKey, JSON.stringify(items));
  } catch {
    // ignore storage errors
  }
}

