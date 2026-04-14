export interface TenorGifItem {
  id: string;
  title: string;
  url: string;
  previewUrl: string;
}

export interface TenorSearchResult {
  items: TenorGifItem[];
  /** Пользовательское сообщение: нет ключа, ответ Tenor, сеть */
  error?: string;
}

const TENOR_API_KEY = (import.meta.env.VITE_TENOR_API_KEY as string | undefined)?.trim();
const TENOR_CLIENT_KEY = (import.meta.env.VITE_TENOR_CLIENT_KEY as string | undefined)?.trim() ?? 'msghub-web';

/** Запрос нескольких форматов, URL в ответе берём с fallback на gif / nanogif. */
const MEDIA_FILTER = 'tinygif,nanogif,gif';

type MediaFormats = {
  tinygif?: { url?: string };
  nanogif?: { url?: string };
  gif?: { url?: string };
};

function pickGifUrl(m?: MediaFormats): string | undefined {
  return m?.tinygif?.url ?? m?.gif?.url ?? m?.nanogif?.url;
}

function pickPreviewUrl(m?: MediaFormats, gifUrl?: string): string | undefined {
  return m?.nanogif?.url ?? m?.tinygif?.url ?? m?.gif?.url ?? gifUrl;
}

export async function searchTenorGifs(query: string, limit = 12): Promise<TenorSearchResult> {
  const q = query.trim();
  if (!q) return { items: [] };

  if (!TENOR_API_KEY) {
    return {
      items: [],
      error:
        'Для поиска GIF укажите VITE_TENOR_API_KEY в .env (ключ Tenor API в Google Cloud Console).',
    };
  }

  const url = new URL('https://tenor.googleapis.com/v2/search');
  url.searchParams.set('q', q);
  url.searchParams.set('key', TENOR_API_KEY);
  url.searchParams.set('client_key', TENOR_CLIENT_KEY);
  url.searchParams.set('limit', String(limit));
  url.searchParams.set('media_filter', MEDIA_FILTER);

  let res: Response;
  try {
    res = await fetch(url.toString());
  } catch {
    return { items: [], error: 'Не удалось связаться с Tenor. Проверьте сеть.' };
  }

  let data: unknown;
  try {
    data = await res.json();
  } catch {
    return { items: [], error: 'Некорректный ответ Tenor.' };
  }

  const errBody = data as { error?: { message?: string; code?: number } };
  if (!res.ok || errBody.error) {
    const msg = errBody.error?.message ?? `Tenor ответил с кодом ${res.status}.`;
    return { items: [], error: msg };
  }

  const body = data as {
    results?: Array<{
      id?: string;
      content_description?: string;
      media_formats?: MediaFormats;
    }>;
  };

  const items = (body.results ?? [])
    .map((item) => {
      const mf = item.media_formats;
      const gifUrl = pickGifUrl(mf);
      const previewUrl = pickPreviewUrl(mf, gifUrl);
      if (!gifUrl || !previewUrl) return null;
      return {
        id: item.id ?? crypto.randomUUID(),
        title: item.content_description ?? 'gif',
        url: gifUrl,
        previewUrl,
      };
    })
    .filter((item): item is TenorGifItem => item != null);

  return { items };
}
