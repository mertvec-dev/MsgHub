import { isAxiosError } from 'axios';

export function apiErrorDetail(err: unknown, fallback: string): string {
  if (isAxiosError(err) && !err.response) {
    if (err.code === 'ERR_NETWORK' || err.message === 'Network Error') {
      return 'Нет ответа от сервера. Проверьте, что backend запущен, и повторите.';
    }
  }
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

