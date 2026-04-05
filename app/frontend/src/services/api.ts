import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios';

const API_URL = 'http://localhost:8000';

/** Один общий refresh на параллельные 401 */
let refreshInflight: Promise<void> | null = null;

async function runRefresh(): Promise<void> {
  const rt = localStorage.getItem('refresh_token');
  if (!rt) throw new Error('no_refresh_token');
  const { data } = await axios.post<AuthResponse>(
    `${API_URL}/auth/refresh`,
    { refresh_token: rt },
    { headers: { 'Content-Type': 'application/json' } }
  );
  localStorage.setItem('access_token', data.access_token);
  localStorage.setItem('refresh_token', data.refresh_token);
  window.dispatchEvent(
    new CustomEvent<AuthResponse>('msghub:tokens-refreshed', { detail: data })
  );
}

function refreshAccessToken(): Promise<void> {
  if (!refreshInflight) {
    refreshInflight = (async () => {
      try {
        await runRefresh();
      } finally {
        refreshInflight = null;
      }
    })();
  }
  return refreshInflight;
}

function isAuthPublicPath(url: string): boolean {
  return (
    url.includes('/auth/login') ||
    url.includes('/auth/register') ||
    url.includes('/auth/refresh')
  );
}

export interface User {
  id: number;
  nickname: string;
  username: string;
  email?: string;
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user_id: number;
}

export interface Room {
  id: number;
  name: string | null;
  type: 'direct' | 'group';
  created_by: number;
  created_at: string;
  updated_at: string;
  last_message?: string | null;
  last_message_sender?: string | null;
  partner_id?: number | null;
  partner_nickname?: string | null;
  partner_username?: string | null;
}

/** Заголовок чата в списке слева */
export function getRoomSidebarTitle(room: Room): string {
  if (room.type === 'group') {
    return (room.name && room.name.trim()) || 'Группа';
  }
  return (
    (room.partner_nickname && room.partner_nickname.trim()) ||
    room.partner_username ||
    room.name ||
    'Личная переписка'
  );
}

export interface Message {
  id: number;
  room_id: number;
  sender_id: number;
  sender_nickname?: string;
  content: string;
  is_edited: boolean;
  edited_at: string | null;
  created_at: string;
  is_read?: boolean;
}

export interface Friendship {
  id: number;
  sender_id: number;
  receiver_id: number;
  status: 'pending' | 'accepted' | 'blocked';
  created_at: string;
  updated_at: string;
}

const api = axios.create({
  baseURL: API_URL,
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) config.headers.Authorization = 'Bearer ' + token;
  return config;
});

api.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    const original = error.config as (InternalAxiosRequestConfig & { _retry?: boolean }) | undefined;
    const status = error.response?.status;

    if (status !== 401 || !original) {
      return Promise.reject(error);
    }
    if (original._retry) {
      return Promise.reject(error);
    }
    const path = original.url ?? '';
    if (isAuthPublicPath(path)) {
      return Promise.reject(error);
    }

    original._retry = true;
    try {
      await refreshAccessToken();
      const token = localStorage.getItem('access_token');
      if (token) {
        original.headers.Authorization = 'Bearer ' + token;
      }
      return api(original);
    } catch {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      window.dispatchEvent(new Event('msghub:auth-failed'));
      return Promise.reject(error);
    }
  }
);

export const auth = {
  register: (n: string, u: string, p: string, e?: string) =>
    api.post<AuthResponse>('/auth/register', { nickname: n, username: u, password: p, email: e }),
  login: (u: string, p: string) =>
    api.post<AuthResponse>('/auth/login', { username: u, password: p }),
  /** Ручной refresh (редко нужен; основной путь — перехватчик 401) */
  refresh: () => refreshAccessToken(),
  getSessions: () => api.get('/auth/sessions'),
};

export const rooms = {
  getMyRooms: () => api.get<Room[]>('/rooms/my'),
  getMembers: (roomId: number) => api.get(`/rooms/${roomId}/members`),
  createGroup: (name: string, user_ids: number[] = []) =>
    api.post<Room>('/rooms/create', { name, type: 'group', user_ids }),
  createDirect: (id: number) => api.post<Room>(`/rooms/direct/${id}`, {}),
  invite: (roomId: number, userId: number) =>
    api.post('/rooms/invite', null, { params: { room_id: roomId, user_id: userId } }),
  kick: (roomId: number, userId: number) =>
    api.delete('/rooms/kick', { params: { room_id: roomId, user_id: userId } }),
  leave: (roomId: number) => api.post(`/rooms/leave/${roomId}`),
  clearHistory: (roomId: number) => api.post(`/rooms/clear/${roomId}`, {}),
  deleteSelf: (roomId: number) => api.delete(`/rooms/self/${roomId}`),
  ban: (roomId: number, userId: number) =>
    api.post('/rooms/ban', null, { params: { room_id: roomId, user_id: userId } }),
};

export const messages = {
  get: (roomId: number, limit = 50, cursor?: number) =>
    api.get(`/messages/${roomId}`, { params: { limit, cursor } }),
  send: (roomId: number, content: string) =>
    api.post('/messages/send', null, { params: { room_id: roomId, content } }),
  edit: (id: number, content: string) =>
    api.put(`/messages/edit/${id}`, null, { params: { new_content: content } }),
  delete: (id: number) =>
    api.delete(`/messages/${Number(id)}`),
  getUnreadCount: () => api.get('/messages/unread/count'),
  markAsRead: (roomId: number) => api.get(`/messages/read/${roomId}`),
};

export const friends = {
  sendRequest: (username: string) => api.post('/friends/request', { username }),
  accept: (id: number) => api.post(`/friends/accept/${id}`),
  decline: (id: number) => api.post(`/friends/decline/${id}`),
  remove: (id: number) => api.delete(`/friends/${id}`),
  block: (targetUserId: number) => api.post(`/friends/block/${targetUserId}`),
  getFriends: () => api.get('/friends/'),
};
