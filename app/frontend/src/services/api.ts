import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios';

const API_URL =
  import.meta.env.VITE_API_URL ??
  (typeof window !== 'undefined' ? window.location.origin : 'http://localhost');
let accessToken: string | null = null;
const DEVICE_ID_KEY = 'msghub-device-id-v1';

function ensureDeviceId(): string {
  const existing = localStorage.getItem(DEVICE_ID_KEY);
  if (existing) return existing;
  const random = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
  localStorage.setItem(DEVICE_ID_KEY, random);
  return random;
}

function getDeviceMeta(): { device_id: string; device_name: string; device_type: string } {
  const ua = typeof navigator !== 'undefined' ? navigator.userAgent : 'unknown';
  return {
    device_id: ensureDeviceId(),
    device_name: ua.slice(0, 255),
    device_type: 'web',
  };
}

/** Один общий refresh на параллельные 401 */
let refreshInflight: Promise<void> | null = null;

async function runRefresh(): Promise<AuthResponse> {
  const { data } = await axios.post<AuthResponse>(
    `${API_URL}/auth/refresh`,
    {},
    {
      headers: { 'Content-Type': 'application/json' },
      withCredentials: true,
    }
  );
  accessToken = data.access_token;
  window.dispatchEvent(
    new CustomEvent<AuthResponse>('msghub:tokens-refreshed', { detail: data })
  );
  return data;
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
  role?: 'user' | 'moderator' | 'super_admin';
  email?: string;
  avatar_url?: string | null;
  status_message?: string | null;
  profile_tag?: string | null;
  is_admin?: boolean;
  is_banned?: boolean;
  is_active?: boolean;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user_id: number;
}

export interface Room {
  id: number;
  name: string | null;
  type: 'direct' | 'group';
  current_key_version: number;
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
  /** Глобальный тег профиля (назначает админ), виден везде в UI */
  sender_profile_tag?: string | null;
  sender_is_admin?: boolean;
  sender_device_id?: string | null;
  reply_to_message_id?: number | null;
  is_pinned?: boolean;
  pinned_by_user_id?: number | null;
  pinned_at?: string | null;
  pin_note?: string | null;
  content: string;
  nonce: string;
  key_version: number;
  is_edited: boolean;
  edited_at: string | null;
  created_at: string;
  is_read?: boolean;
}

export interface MessageSendPayload {
  room_id: number;
  content: string; // ciphertext
  nonce: string;
  key_version: number;
  sender_device_id?: string;
  reply_to_message_id?: number;
}

export interface MessageEditPayload {
  content: string; // ciphertext
  nonce: string;
  key_version: number;
}

export interface SessionInfo {
  id: number;
  device_id?: string | null;
  device_info?: string | null;
  ip_address?: string | null;
  created_at: string;
  expires_at: string;
  last_active_at: string;
}

export interface SessionListResponse {
  sessions: SessionInfo[];
}

export interface AdminOverview {
  users_total: number;
  admins_total: number;
  banned_total: number;
  rooms_total: number;
  messages_total: number;
}

export interface AdminAuditLogItem {
  id: number;
  actor_user_id: number;
  target_user_id?: number | null;
  action: string;
  details?: string | null;
  ip_address?: string | null;
  user_agent?: string | null;
  created_at: string;
}

export interface SecurityEventItem {
  id: number;
  user_id?: number | null;
  event_type: string;
  severity: string;
  details?: string | null;
  ip_address?: string | null;
  user_agent?: string | null;
  created_at: string;
}

export interface DeviceKeyItem {
  user_id: number;
  device_id: string;
  algorithm: string;
  public_key: string;
}

export interface PeerDeviceKeysResponse {
  user_id: number;
  devices: DeviceKeyItem[];
}

export interface DirectE2EReadinessResponse {
  peer_user_id: number;
  direct_room_id: number | null;
  friendship_confirmed: boolean;
  viewer_has_device_key: boolean;
  peer_has_device_key: boolean;
  ready: boolean;
  reason?: string | null;
}

export interface Friendship {
  id: number;
  sender_id: number;
  receiver_id: number;
  status: 'pending' | 'accepted' | 'blocked';
  blocked_by_me?: boolean;
  created_at: string;
  updated_at: string;
}

export interface RoomMemberInfo {
  id: number;
  nickname: string;
  username: string;
  is_admin?: boolean;
  profile_tag?: string | null;
}

export interface E2EPublicKeyResponse {
  user_id: number;
  algorithm: string;
  public_key: string;
}

export interface RoomKeyEnvelopeItem {
  user_id: number;
  encrypted_key: string;
  algorithm: string;
}

export interface RoomKeyEnvelopeUpsertPayload {
  key_version: number;
  envelopes: RoomKeyEnvelopeItem[];
}

export interface RoomKeyEnvelopeResponse {
  room_id: number;
  user_id: number;
  key_version: number;
  encrypted_key: string;
  algorithm: string;
}

export interface RoomKeyRotateResponse {
  room_id: number;
  current_key_version: number;
}

const api = axios.create({
  baseURL: API_URL,
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true,
});

api.interceptors.request.use((config) => {
  if (accessToken) config.headers.Authorization = 'Bearer ' + accessToken;
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
      if (accessToken) {
        original.headers.Authorization = 'Bearer ' + accessToken;
      }
      return api(original);
    } catch {
      accessToken = null;
      window.dispatchEvent(new Event('msghub:auth-failed'));
      return Promise.reject(error);
    }
  }
);

export const auth = {
  register: (n: string, u: string, p: string) =>
    api.post<AuthResponse>('/auth/register', { nickname: n, username: u, password: p }, {
      headers: {
        'X-Device-Id': getDeviceMeta().device_id,
        'X-Device-Name': getDeviceMeta().device_name,
        'X-Device-Type': 'web',
      },
    }),
  login: (u: string, p: string) =>
    api.post<AuthResponse>('/auth/login', { username: u, password: p, ...getDeviceMeta() }),
  /** Ручной refresh (редко нужен; основной путь — перехватчик 401) */
  refresh: () => refreshAccessToken(),
  logout: () => api.post('/auth/logout', {}),
  getSessions: () => api.get<SessionListResponse>('/auth/sessions'),
  revokeSession: (sessionId: number) => api.delete(`/auth/sessions/${sessionId}`),
  revokeOthers: () => api.post('/auth/sessions/revoke-others', {}),
  getMe: () => api.get<User>('/auth/me'),
  updateMe: (payload: Partial<Pick<User, 'nickname' | 'email' | 'avatar_url' | 'status_message' | 'profile_tag'>>) =>
    api.patch<User>('/auth/me', payload),
  adminListUsers: () => api.get<User[]>('/auth/admin/users'),
  /** Тот же endpoint, что и список, с query `q` — поиск (см. backend). */
  adminSearchUsers: (q: string, limit = 50) =>
    api.get<User[]>('/auth/admin/users', { params: { q, limit } }),
  adminGrant: (userId: number) => api.post<User>(`/auth/admin/users/${userId}/grant-admin`, {}),
  adminRevoke: (userId: number) => api.post<User>(`/auth/admin/users/${userId}/revoke-admin`, {}),
  adminBan: (userId: number) => api.post<User>(`/auth/admin/users/${userId}/ban`, {}),
  adminUnban: (userId: number) => api.post<User>(`/auth/admin/users/${userId}/unban`, {}),
  adminDeactivate: (userId: number) => api.post<User>(`/auth/admin/users/${userId}/deactivate`, {}),
  adminOverview: () => api.get<AdminOverview>('/auth/admin/overview'),
  adminSetRole: (userId: number, role: 'user' | 'moderator' | 'super_admin') =>
    api.post<User>(`/auth/admin/users/${userId}/role`, { role }),
  adminGrantPermission: (userId: number, permission: string) =>
    api.post(`/auth/admin/users/${userId}/permissions/grant`, { permission }),
  adminRevokePermission: (userId: number, permission: string) =>
    api.post(`/auth/admin/users/${userId}/permissions/revoke`, { permission }),
  adminSetUserTag: (userId: number, profile_tag: string) =>
    api.post<User>(`/auth/admin/users/${userId}/tag`, { profile_tag }),
  adminClearUserTag: (userId: number) =>
    api.post<User>(`/auth/admin/users/${userId}/tag`, { profile_tag: null }),
  adminDeleteUser: (userId: number) =>
    api.delete(`/auth/admin/users/${userId}`),
  adminMyPermissions: () => api.get<{ permissions: string[] }>('/auth/admin/me/permissions'),
  adminAuditLogs: (limit = 100) => api.get<AdminAuditLogItem[]>('/auth/admin/audit-logs', { params: { limit } }),
  adminSecurityEvents: (limit = 100) => api.get<SecurityEventItem[]>('/auth/admin/security-events', { params: { limit } }),
};

export const e2e = {
  upsertPublicKey: (publicKey: string, algorithm = 'p256-ecdh-v1') =>
    api.post<E2EPublicKeyResponse>('/auth/e2e/public-key', {
      public_key: publicKey,
      algorithm,
    }),
  getPublicKey: (userId: number) =>
    api.get<E2EPublicKeyResponse>(`/auth/e2e/public-key/${userId}`),
  upsertDeviceKey: (publicKey: string, algorithm = 'p256-ecdh-v1') =>
    api.post('/auth/e2e/device-key', {
      ...getDeviceMeta(),
      public_key: publicKey,
      algorithm,
    }),
  getPeerDeviceKeys: (userId: number) =>
    api.get<PeerDeviceKeysResponse>(`/auth/e2e/device-keys/${userId}`),
  getDirectReadiness: (peerUserId: number) =>
    api.get<DirectE2EReadinessResponse>(`/auth/e2e/direct-readiness/${peerUserId}`),
  forceSyncWithPeer: (peerUserId: number) =>
    api.get(`/auth/e2e/direct-readiness/${peerUserId}`),
  getDeviceId: () => ensureDeviceId(),
};

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export const rooms = {
  getMyRooms: () => api.get<Room[]>('/rooms/my'),
  getMembers: (roomId: number) => api.get<RoomMemberInfo[]>(`/rooms/${roomId}/members`),
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
  mute: (roomId: number, userId: number, minutes: number, reason?: string) =>
    api.post('/rooms/mute', { user_id: userId, minutes, reason }, { params: { room_id: roomId } }),
  unmute: (roomId: number, userId: number) =>
    api.post('/rooms/unmute', null, { params: { room_id: roomId, user_id: userId } }),
  upsertRoomKeys: (roomId: number, payload: RoomKeyEnvelopeUpsertPayload) =>
    api.post(`/rooms/${roomId}/keys/upsert`, payload),
  getMyRoomKey: (roomId: number) =>
    api.get<RoomKeyEnvelopeResponse>(`/rooms/${roomId}/keys/my`),
  rotateRoomKey: (roomId: number) =>
    api.post<RoomKeyRotateResponse>(`/rooms/${roomId}/keys/rotate`, {}),
};

export const messages = {
  get: (roomId: number, limit = 50, cursor?: number) =>
    api.get(`/messages/${roomId}`, { params: { limit, cursor } }),
  send: (payload: MessageSendPayload) =>
    api.post('/messages/send', payload),
  edit: (id: number, payload: MessageEditPayload) =>
    api.put(`/messages/edit/${id}`, payload),
  delete: (id: number) =>
    api.delete(`/messages/${Number(id)}`),
  getUnreadCount: () => api.get('/messages/unread/count'),
  markAsRead: (roomId: number) => api.get(`/messages/read/${roomId}`),
  pin: (roomId: number, messageId: number, pin_note?: string) =>
    api.post(`/messages/pin/${roomId}/${messageId}`, { pin_note }),
  unpin: (roomId: number, messageId: number) =>
    api.post(`/messages/unpin/${roomId}/${messageId}`, {}),
};

export const friends = {
  sendRequest: (username: string) => api.post('/friends/request', { username }),
  accept: (id: number) => api.post(`/friends/accept/${id}`),
  decline: (id: number) => api.post(`/friends/decline/${id}`),
  remove: (id: number) => api.delete(`/friends/${id}`),
  block: (targetUserId: number) => api.post(`/friends/block/${targetUserId}`),
  unblock: (targetUserId: number) => api.post(`/friends/unblock/${targetUserId}`),
  getFriends: () => api.get('/friends/'),
};
