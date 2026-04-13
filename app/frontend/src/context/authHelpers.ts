export function parseUserId(token: string | null): number | null {
  if (!token) return null;
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const payload = JSON.parse(atob(parts[1]));
    const raw = payload.user_id;
    if (raw == null) return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  } catch {
    return null;
  }
}

/** user_id из тела ответа или из JWT (если backend не отдал поле). */
export function userIdFromAuthPayload(data: { access_token: string; user_id?: number }): number | null {
  const raw = data.user_id;
  if (raw != null) {
    const n = Number(raw);
    if (Number.isFinite(n)) return n;
  }
  return parseUserId(data.access_token);
}

