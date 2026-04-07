const ALIASES_KEY = 'msghub-local-aliases-v1';

export type LocalAliases = Record<number, string>;

export function loadAliases(): LocalAliases {
  try {
    const raw = localStorage.getItem(ALIASES_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const out: LocalAliases = {};
    for (const [k, v] of Object.entries(parsed)) {
      const id = Number(k);
      if (!Number.isFinite(id)) continue;
      if (typeof v !== 'string') continue;
      out[id] = v;
    }
    return out;
  } catch {
    return {};
  }
}

export function saveAliases(aliases: LocalAliases): void {
  localStorage.setItem(ALIASES_KEY, JSON.stringify(aliases));
}

export function setAlias(userId: number, alias: string): LocalAliases {
  const current = loadAliases();
  const next = { ...current };
  const trimmed = alias.trim();
  if (trimmed) next[userId] = trimmed;
  else delete next[userId];
  saveAliases(next);
  return next;
}

export function getAlias(userId: number | null | undefined): string | null {
  if (userId == null) return null;
  const all = loadAliases();
  const value = all[userId];
  return value?.trim() ? value : null;
}

