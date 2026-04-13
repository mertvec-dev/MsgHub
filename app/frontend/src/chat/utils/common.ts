import { getAlias } from '../../services/localAliases';

export const MAX_MESSAGE_CHARS = 1800;

/** API/WS могут отдавать id числом или строкой. */
export function sameId(a: unknown, b: unknown): boolean {
  if (a == null || b == null) return false;
  return Number(a) === Number(b);
}

export function encryptedPlaceholder(): string {
  return '🔒 Encrypted message';
}

export function looksEncryptedPayload(value: string | null | undefined): boolean {
  if (!value) return false;
  const trimmed = value.trim();
  return trimmed.length >= 24 && /^[A-Za-z0-9+/=]+$/.test(trimmed);
}

export function preferAlias(userId: number | null | undefined, fallback: string): string {
  const alias = getAlias(userId);
  return alias || fallback;
}

export function previewCacheStorageKey(userId: number | null | undefined): string {
  return `msghub-last-preview-v1:${userId ?? 'anon'}`;
}

export function pendingOutboxStorageKey(userId: number | null | undefined): string {
  return `msghub-pending-outbox-v1:${userId ?? 'anon'}`;
}

