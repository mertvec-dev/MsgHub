export interface TenorGifItem {
  id: string;
  title: string;
  url: string;
  previewUrl: string;
}

const TENOR_API_KEY = import.meta.env.VITE_TENOR_API_KEY ?? 'LIVDSRZULELA';
const TENOR_CLIENT_KEY = import.meta.env.VITE_TENOR_CLIENT_KEY ?? 'msghub-web';

export async function searchTenorGifs(query: string, limit = 12): Promise<TenorGifItem[]> {
  const q = query.trim();
  if (!q) return [];
  const url = new URL('https://tenor.googleapis.com/v2/search');
  url.searchParams.set('q', q);
  url.searchParams.set('key', TENOR_API_KEY);
  url.searchParams.set('client_key', TENOR_CLIENT_KEY);
  url.searchParams.set('limit', String(limit));
  url.searchParams.set('media_filter', 'tinygif');

  const res = await fetch(url.toString());
  if (!res.ok) return [];
  const data = (await res.json()) as {
    results?: Array<{
      id?: string;
      content_description?: string;
      media_formats?: {
        tinygif?: { url?: string };
        nanogif?: { url?: string };
      };
    }>;
  };
  return (data.results ?? [])
    .map((item) => {
      const gifUrl = item.media_formats?.tinygif?.url;
      const previewUrl = item.media_formats?.nanogif?.url ?? gifUrl;
      if (!gifUrl || !previewUrl) return null;
      return {
        id: item.id ?? crypto.randomUUID(),
        title: item.content_description ?? 'gif',
        url: gifUrl,
        previewUrl,
      };
    })
    .filter((item): item is TenorGifItem => item != null);
}
