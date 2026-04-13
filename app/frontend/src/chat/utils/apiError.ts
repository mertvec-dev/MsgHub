export function apiErrorDetail(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((item: unknown) =>
      typeof item === 'object' && item !== null && 'msg' in item
        ? String((item as { msg: string }).msg)
        : String(item)
    );
    return parts.filter(Boolean).join(' ') || fallback;
  }
  const message = (err as { message?: string })?.message;
  return message || fallback;
}

