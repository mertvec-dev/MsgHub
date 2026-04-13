export function loadPreviewCache(storageKey: string): Map<number, string> {
  try {
    const raw = localStorage.getItem(storageKey);
    if (!raw) return new Map();

    const parsed = JSON.parse(raw) as Record<string, string>;
    const map = new Map<number, string>();
    Object.entries(parsed).forEach(([key, value]) => {
      const id = Number(key);
      if (!Number.isNaN(id) && typeof value === 'string' && value.trim()) {
        map.set(id, value);
      }
    });
    return map;
  } catch {
    return new Map();
  }
}

export function savePreviewCache(storageKey: string, cache: Map<number, string>): void {
  try {
    const obj = Object.fromEntries(cache.entries());
    localStorage.setItem(storageKey, JSON.stringify(obj));
  } catch {
    // ignore storage errors
  }
}

