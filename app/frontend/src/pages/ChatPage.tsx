import { useState, useEffect, useRef, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import {
  auth,
  rooms,
  messages,
  friends,
  e2e,
  getRoomSidebarTitle,
  getAccessToken,
  type Room,
  type Message,
} from '../services/api';
import {
  ensureOwnPublicKey,
  encryptForPeer,
  decryptFromPeer,
  encryptForRoom,
  decryptFromRoom,
  generateRoomKey,
  saveRoomKey,
  loadRoomKey,
  encryptRoomKeyForMember,
  decryptRoomKeyEnvelope,
  hasLocalPrivateKey,
  clearLocalPrivateKey,
  warmupPeerDeviceKey,
  markPeerWarm,
} from '../services/e2e';
import { getAlias, setAlias as setLocalAlias } from '../services/localAliases';
import '../styles/ChatPage.css';

interface FriendRequest {
  id: number;
  sender_id: number;
  receiver_id: number;
  nickname?: string;
  username?: string;
  partner_id?: number;
  status: 'pending' | 'accepted' | 'blocked';
}

interface Friend {
  id: number;
  nickname: string;
  username: string;
  is_online: boolean;
}

interface RoomMember {
  id: number;
  nickname: string;
  username: string;
}

interface PendingOutboxItem {
  local_id: number;
  room_id: number;
  text: string;
  created_at: string;
  attempts: number;
}

/** API/WS могут отдавать id числом или строкой — строгое === ломало удаление и обновление списка */
function sameId(a: unknown, b: unknown): boolean {
  if (a == null || b == null) return false;
  return Number(a) === Number(b);
}

function apiErrorDetail(err: unknown, fallback: string): string {
  const d = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) {
    const parts = d.map((item: unknown) =>
      typeof item === 'object' && item !== null && 'msg' in item
        ? String((item as { msg: string }).msg)
        : String(item)
    );
    return parts.filter(Boolean).join(' ') || fallback;
  }
  return fallback;
}

function randomNonce(length = 12): string {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  let out = '';
  for (let i = 0; i < bytes.length; i++) out += alphabet[bytes[i] % alphabet.length];
  return out;
}

function encryptedPlaceholder(): string {
  return '🔒 Encrypted message';
}

function previewCacheStorageKey(userId: number | null | undefined): string {
  return `msghub-last-preview-v1:${userId ?? 'anon'}`;
}

function pendingOutboxStorageKey(userId: number | null | undefined): string {
  return `msghub-pending-outbox-v1:${userId ?? 'anon'}`;
}

function looksEncryptedPayload(value: string | null | undefined): boolean {
  if (!value) return false;
  const trimmed = value.trim();
  // Грубый эвристический детект base64/ciphertext, чтобы не показывать мусор в превью.
  return trimmed.length >= 24 && /^[A-Za-z0-9+/=]+$/.test(trimmed);
}

function preferAlias(userId: number | null | undefined, fallback: string): string {
  const alias = getAlias(userId);
  return alias || fallback;
}

export default function ChatPage() {
  const { userId, logout, profileNickname, profileUsername, isAdmin } = useAuth();
  /** Сообщения с API/WebSocket могут отдавать id как number или string — строгое === ломало класс .own. */
  const isMe = useCallback(
    (id: number | string | undefined | null) =>
      userId != null && Number(id) === Number(userId),
    [userId]
  );
  const { showToast } = useToast();
  const [myRooms, setMyRooms] = useState<Room[]>([]);
  const [selectedRoom, setSelectedRoom] = useState<Room | null>(null);
  const [msgList, setMsgList] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [roomMembers, setRoomMembers] = useState<RoomMember[]>([]);
  const [editingMsg, setEditingMsg] = useState<Message | null>(null);
  const [unreadCounts, setUnreadCounts] = useState<Record<number, number>>({});
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMoreMessages, setHasMoreMessages] = useState(true);
  const [lastCursor, setLastCursor] = useState<number | undefined>(undefined);
  const lastCursorRef = useRef<number | undefined>(undefined);
  const messagesListRef = useRef<HTMLDivElement>(null);
  const myRoomsRef = useRef<Room[]>([]);

  // Меню
  const [activeMenu, setActiveMenu] = useState<'chats' | 'friends' | 'requests' | 'settings'>('chats');
  const [friendList, setFriendList] = useState<Friend[]>([]);
  const [friendRequests, setFriendRequests] = useState<FriendRequest[]>([]);
  const [friendUsername, setFriendUsername] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [sendCooldown, setSendCooldown] = useState(false);

  // Создание комнаты
  const [showCreateRoom, setShowCreateRoom] = useState(false);
  const [newRoomName, setNewRoomName] = useState('');
  const [selectedUsers, setSelectedUsers] = useState<number[]>([]);

  // Управление комнатой
  const [showRoomMenu, setShowRoomMenu] = useState(false);
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [inviteUserId, setInviteUserId] = useState('');
  const [showProfileMenu, setShowProfileMenu] = useState(false);

  const messagesEnd = useRef<HTMLDivElement>(null);
  /** Закрытие меню по клику снаружи (см. useEffect ниже) */
  const msgContextMenuRef = useRef<HTMLDivElement>(null);
  const roomSidebarContextMenuRef = useRef<HTMLDivElement>(null);
  const roomHeaderActionsRef = useRef<HTMLDivElement>(null);
  const roomHeaderDropdownRef = useRef<HTMLDivElement>(null);
  const profileMenuRef = useRef<HTMLDivElement>(null);
  const profileButtonRef = useRef<HTMLButtonElement>(null);
  const ws = useRef<WebSocket | null>(null);
  /** Актуальная комната для обработчиков WebSocket (иначе замыкание на старый selectedRoom). */
  const selectedRoomIdRef = useRef<number | null>(null);
  const selectedRoomTypeRef = useRef<'direct' | 'group' | null>(null);
  const selectedRoomRef = useRef<Room | null>(null);
  const activePeerPublicKeyRef = useRef<string | null>(null);
  const roomKeyCacheRef = useRef<Map<string, string>>(new Map());
  const peerPublicKeyCacheRef = useRef<Map<number, string>>(new Map());
  const peerDeviceKeyCacheRef = useRef<Map<number, Map<string, string>>>(new Map());
  const previewCacheRef = useRef<Map<number, string>>(new Map());
  const [activePeerPublicKey, setActivePeerPublicKey] = useState<string | null>(null);
  const [peerKeyRetryTick, setPeerKeyRetryTick] = useState(0);
  const [hasE2EKey, setHasE2EKey] = useState<boolean>(false);
  const [directHandshakeReady, setDirectHandshakeReady] = useState<boolean>(false);
  const [directHandshakeBusy, setDirectHandshakeBusy] = useState<boolean>(false);
  const [groupHandshakeReady, setGroupHandshakeReady] = useState<boolean>(false);
  const [groupHandshakeBusy, setGroupHandshakeBusy] = useState<boolean>(false);
  const [sessions, setSessions] = useState<Array<{ id: number; device_info?: string | null; ip_address?: string | null }>>([]);
  const [profileDraft, setProfileDraft] = useState({
    nickname: '',
    email: '',
    status_message: '',
    profile_tag: '',
  });
  const [adminUsers, setAdminUsers] = useState<Array<{ id: number; username: string; nickname: string; is_admin?: boolean; is_banned?: boolean }>>([]);
  const [pendingOutbox, setPendingOutbox] = useState<PendingOutboxItem[]>([]);
  const pendingOutboxRef = useRef<PendingOutboxItem[]>([]);
  useEffect(() => {
    selectedRoomIdRef.current = selectedRoom?.id ?? null;
    selectedRoomTypeRef.current = selectedRoom?.type ?? null;
    selectedRoomRef.current = selectedRoom ?? null;
  }, [selectedRoom]);
  useEffect(() => {
    activePeerPublicKeyRef.current = activePeerPublicKey;
  }, [activePeerPublicKey]);
  useEffect(() => {
    pendingOutboxRef.current = pendingOutbox;
  }, [pendingOutbox]);
  useEffect(() => {
    try {
      const raw = localStorage.getItem(pendingOutboxStorageKey(userId));
      if (!raw) {
        setPendingOutbox([]);
        return;
      }
      const parsed = JSON.parse(raw) as PendingOutboxItem[];
      if (!Array.isArray(parsed)) {
        setPendingOutbox([]);
        return;
      }
      const sanitized = parsed.filter(
        (item) =>
          item &&
          Number.isFinite(Number(item.local_id)) &&
          Number.isFinite(Number(item.room_id)) &&
          typeof item.text === 'string' &&
          item.text.trim().length > 0
      );
      setPendingOutbox(sanitized);
    } catch {
      setPendingOutbox([]);
    }
  }, [userId]);
  useEffect(() => {
    try {
      localStorage.setItem(
        pendingOutboxStorageKey(userId),
        JSON.stringify(pendingOutbox)
      );
    } catch {
      // ignore storage errors
    }
  }, [pendingOutbox, userId]);

  // Загрузка данных
  const fetchPeerPublicKey = useCallback(async (partnerId: number): Promise<string | null> => {
    const cached = peerPublicKeyCacheRef.current.get(partnerId);
    if (cached) return cached;
    try {
      const res = await e2e.getPublicKey(partnerId);
      const key = res.data.public_key;
      peerPublicKeyCacheRef.current.set(partnerId, key);
      return key;
    } catch {
      return null;
    }
  }, []);

  const warmupPeerDevices = useCallback(async (partnerId: number): Promise<void> => {
    try {
      const deviceRes = await e2e.getPeerDeviceKeys(partnerId);
      const devices = deviceRes.data.devices || [];
      const byDevice = new Map<string, string>();
      await Promise.allSettled(
        devices.map(async (item) => {
          byDevice.set(item.device_id, item.public_key);
          await warmupPeerDeviceKey(item.public_key);
          markPeerWarm(partnerId, item.device_id);
        })
      );
      peerDeviceKeyCacheRef.current.set(partnerId, byDevice);
    } catch {
      // device-key endpoint is best-effort for warmup
    }
  }, []);

  const resolvePeerPublicKey = useCallback(
    async (partnerId: number | null | undefined, senderDeviceId?: string | null): Promise<string | null> => {
      if (partnerId == null) return null;
      if (senderDeviceId) {
        let byDevice = peerDeviceKeyCacheRef.current.get(partnerId);
        if (!byDevice?.has(senderDeviceId)) {
          // Жёсткий догрев: если ключ устройства отправителя не в кэше, тянем список заново.
          await warmupPeerDevices(partnerId);
          byDevice = peerDeviceKeyCacheRef.current.get(partnerId);
        }
        if (byDevice?.has(senderDeviceId)) {
          return byDevice.get(senderDeviceId) || null;
        }
      }
      return fetchPeerPublicKey(partnerId);
    },
    [fetchPeerPublicKey, warmupPeerDevices]
  );

  const loadRooms = async () => {
    try {
      const r = await rooms.getMyRooms();
      const hydrated = r.data.map((room) => {
        const cached = previewCacheRef.current.get(room.id);
        if (cached && room.type === 'direct') {
          return {
            ...room,
            last_message: cached,
          };
        }
        return room;
      });
      setMyRooms(hydrated);
      // Прогреваем public keys для direct-чатов в фоне,
      // чтобы при открытии чата не было задержки/состояния "нет ключа".
      const partners = r.data
        .filter((room) => room.type === 'direct' && room.partner_id != null)
        .map((room) => Number(room.partner_id));
      void Promise.allSettled(
        [...new Set(partners)].map(async (partnerId) => {
          await fetchPeerPublicKey(partnerId);
          await warmupPeerDevices(partnerId);
        })
      );
    } catch (e) {
      console.error('Ошибка загрузки комнат:', e);
    }
  };

  useEffect(() => {
    myRoomsRef.current = myRooms;
  }, [myRooms]);
  useEffect(() => {
    lastCursorRef.current = lastCursor;
  }, [lastCursor]);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(previewCacheStorageKey(userId));
      if (!raw) {
        previewCacheRef.current = new Map();
        return;
      }
      const parsed = JSON.parse(raw) as Record<string, string>;
      const map = new Map<number, string>();
      Object.entries(parsed).forEach(([key, value]) => {
        const id = Number(key);
        if (!Number.isNaN(id) && typeof value === 'string' && value.trim()) {
          map.set(id, value);
        }
      });
      previewCacheRef.current = map;
    } catch {
      previewCacheRef.current = new Map();
    }
  }, [userId]);

  const setPreviewCache = useCallback((roomId: number, preview: string) => {
    if (!preview.trim()) return;
    previewCacheRef.current.set(roomId, preview);
    try {
      const obj = Object.fromEntries(previewCacheRef.current.entries());
      localStorage.setItem(previewCacheStorageKey(userId), JSON.stringify(obj));
    } catch {
      // ignore storage errors
    }
  }, [userId]);

  const getRoomPreview = useCallback((room: Room): string => {
    const cached = previewCacheRef.current.get(room.id);
    if (cached) return cached;
    if (!room.last_message) return 'Нет сообщений';
    if (looksEncryptedPayload(room.last_message)) {
      return room.last_message_sender
        ? `🔒 ${room.last_message_sender}: encrypted`
        : '🔒 Encrypted message';
    }
    return room.last_message;
  }, []);

  const loadFriendsData = async () => {
    try {
      const r = await friends.getFriends();
      const allFriends = r.data.friends || [];
      const pending = allFriends.filter((f: { status: string }) => f.status === 'pending');
      const accepted = allFriends.filter((f: { status: string }) => f.status === 'accepted');
      setFriendRequests(pending);
      setFriendList(accepted.map((f: { partner_id: number; nickname: string; username: string; is_online: boolean }) => ({
        id: f.partner_id,
        nickname: f.nickname,
        username: f.username,
        is_online: f.is_online,
      })));
    } catch (e) {
      console.error(e);
    }
  };

  const loadUnreadCounts = async () => {
    try {
      const r = await messages.getUnreadCount();
      setUnreadCounts(r.data.unread_counts || {});
    } catch (e) {
      console.error('Ошибка загрузки непрочитанных:', e);
    }
  };

  const loadRoomMembers = async (roomId: number) => {
    try {
      const r = await rooms.getMembers(roomId);
      setRoomMembers(r.data);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    loadRooms();
    loadFriendsData();
    loadUnreadCounts();
    setHasE2EKey(hasLocalPrivateKey());
    void auth.getSessions().then((res) => setSessions(res.data.sessions || [])).catch(() => {});
    void auth.getMe().then((res) => {
      setProfileDraft({
        nickname: res.data.nickname || '',
        email: res.data.email || '',
        status_message: res.data.status_message || '',
        profile_tag: res.data.profile_tag || '',
      });
    }).catch(() => {});
    if (isAdmin) {
      void auth.adminListUsers().then((res) => setAdminUsers(res.data || [])).catch(() => {});
    }
  }, []);

  // Гарантируем, что у текущего клиента есть E2E public key на сервере.
  useEffect(() => {
    if (!userId) return;
    void (async () => {
      try {
        const { publicKeyB64 } = await ensureOwnPublicKey();
        await e2e.upsertPublicKey(publicKeyB64);
        await e2e.upsertDeviceKey(publicKeyB64);
        setHasE2EKey(true);
      } catch (err) {
        console.error('Не удалось инициализировать E2E ключ:', err);
      }
    })();
  }, [userId]);

  // Для direct-чата подтягиваем публичный ключ собеседника.
  useEffect(() => {
    const partnerId = selectedRoom?.partner_id;
    if (!selectedRoom || selectedRoom.type !== 'direct' || partnerId == null) {
      setActivePeerPublicKey(null);
      setDirectHandshakeReady(false);
      return;
    }
    setDirectHandshakeBusy(true);
    setDirectHandshakeReady(false);
    void (async () => {
      const cached = peerPublicKeyCacheRef.current.get(partnerId);
      if (cached) {
        setActivePeerPublicKey(cached);
        await warmupPeerDevices(partnerId);
        setDirectHandshakeReady(true);
        setDirectHandshakeBusy(false);
        return;
      }
      for (let attempt = 1; attempt <= 3; attempt++) {
        try {
          const key = await fetchPeerPublicKey(partnerId);
          if (!key) throw new Error('no-key');
          setActivePeerPublicKey(key);
          await warmupPeerDevices(partnerId);
          setDirectHandshakeReady(true);
          setDirectHandshakeBusy(false);
          return;
        } catch (err) {
          if (attempt === 3) {
            setActivePeerPublicKey(null);
            setDirectHandshakeBusy(false);
            console.error('Не удалось получить public key собеседника:', err);
            return;
          }
          await new Promise((resolve) => setTimeout(resolve, 800));
        }
      }
    })();
  }, [selectedRoom?.id, selectedRoom?.type, selectedRoom?.partner_id, peerKeyRetryTick]);

  // Если ключ собеседника временно недоступен (еще не загрузился/не опубликован),
  // периодически повторяем попытку, чтобы шифрование/дешифрование оживало без перезагрузки страницы.
  useEffect(() => {
    if (!selectedRoom || selectedRoom.type !== 'direct' || selectedRoom.partner_id == null) return;
    if (directHandshakeReady) return;
    const t = setTimeout(() => setPeerKeyRetryTick((v) => v + 1), 3000);
    return () => clearTimeout(t);
  }, [selectedRoom?.id, selectedRoom?.type, selectedRoom?.partner_id, directHandshakeReady]);

  useEffect(() => {
    if (!selectedRoom || selectedRoom.type !== 'direct') return;
    if (!activePeerPublicKey) return;
    if (directHandshakeReady) return;
    const partnerId = selectedRoom.partner_id;
    if (partnerId == null) return;
    void (async () => {
      setDirectHandshakeBusy(true);
      await warmupPeerDevices(partnerId);
      setDirectHandshakeReady(true);
      setDirectHandshakeBusy(false);
    })();
  }, [selectedRoom?.id, selectedRoom?.type, selectedRoom?.partner_id, activePeerPublicKey, directHandshakeReady, warmupPeerDevices]);

  const getCachedRoomKey = useCallback((roomId: number, keyVersion: number): string | null => {
    const cacheKey = `${roomId}:${keyVersion}`;
    const cached = roomKeyCacheRef.current.get(cacheKey);
    if (cached) return cached;
    const persisted = loadRoomKey(roomId, keyVersion);
    if (persisted) {
      roomKeyCacheRef.current.set(cacheKey, persisted);
      return persisted;
    }
    return null;
  }, []);

  const putCachedRoomKey = useCallback((roomId: number, keyVersion: number, roomKeyB64: string) => {
    const cacheKey = `${roomId}:${keyVersion}`;
    roomKeyCacheRef.current.set(cacheKey, roomKeyB64);
    saveRoomKey(roomId, keyVersion, roomKeyB64);
  }, []);

  const ensureGroupRoomKey = useCallback(async (room: Room, keyVersion: number): Promise<string | null> => {
    if (room.type !== 'group') return null;

    const existing = getCachedRoomKey(room.id, keyVersion);
    if (existing) return existing;

    // Пробуем получить и расшифровать конверт текущей версии с сервера.
    if (keyVersion === room.current_key_version) {
      try {
        const envelopeRes = await rooms.getMyRoomKey(room.id);
        const roomKeyB64 = await decryptRoomKeyEnvelope(envelopeRes.data.encrypted_key);
        putCachedRoomKey(room.id, envelopeRes.data.key_version, roomKeyB64);
        if (envelopeRes.data.key_version === keyVersion) return roomKeyB64;
      } catch {
        // Если конверта нет, попробуем bootstrap новой версии ниже.
      }
    }

    // Для старых версий без локального кэша ключ получить неоткуда (API отдает только current).
    if (keyVersion !== room.current_key_version) return null;

    // Bootstrap: генерируем room-key и разворачиваем конверты на всех участников.
    const membersRes = await rooms.getMembers(room.id);
    const members = (membersRes.data || []) as RoomMember[];
    if (!members.length) throw new Error('Не удалось загрузить участников комнаты');

    const roomKeyB64 = generateRoomKey();
    const envelopes = await Promise.all(
      members.map(async (member) => {
        const pk = await e2e.getPublicKey(member.id);
        const encryptedKey = await encryptRoomKeyForMember(roomKeyB64, pk.data.public_key);
        return {
          user_id: member.id,
          encrypted_key: encryptedKey,
          algorithm: 'p256-ecdh-v1',
        };
      })
    );

    await rooms.upsertRoomKeys(room.id, {
      key_version: keyVersion,
      envelopes,
    });
    putCachedRoomKey(room.id, keyVersion, roomKeyB64);
    return roomKeyB64;
  }, [getCachedRoomKey, putCachedRoomKey]);

  const WS_URL =
    import.meta.env.VITE_WS_URL ??
    (typeof window !== 'undefined'
      ? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`
      : 'ws://localhost/ws');

  // WebSocket подключение
  useEffect(() => {
    if (!userId) return;
    const token = getAccessToken();
    if (!token) {
      console.error("❌ Нет access token в памяти, WebSocket не подключится");
      return;
    }

    console.log("🔌 Подключение WebSocket...", WS_URL);
    ws.current = new WebSocket(WS_URL);

    const sendJoinRoom = () => {
      const rid = selectedRoomIdRef.current;
      if (rid == null || !ws.current || ws.current.readyState !== WebSocket.OPEN) return;
      ws.current.send(JSON.stringify({ action: 'join_room', room_id: rid }));
    };

    ws.current.onopen = () => {
      console.log('✅ Соединение открыто, отправляю auth...');
      ws.current?.send(JSON.stringify({ action: 'auth', token }));
    };

    ws.current.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        const roomOpen = selectedRoomIdRef.current;

        if (data.action === 'authenticated') {
          sendJoinRoom();
          return;
        }

        if (data.action === 'joined_room') {
          console.log('✅ Комната для WS:', data.room_id);
        }

        console.log("📥 WebSocket:", data.action, data);
        switch (data.action) {
          case 'new_message':
            if (sameId(data.room_id, roomOpen)) {
              const nickname = data.sender_nickname || (isMe(data.sender_id) ? 'Вы' : 'Пользователь');
              void (async () => {
                let resolvedContent = String(data.content ?? '');
                if (selectedRoomTypeRef.current === 'direct') {
                  if (!activePeerPublicKeyRef.current) {
                    resolvedContent = encryptedPlaceholder();
                  } else {
                    try {
                      const peerKey = await resolvePeerPublicKey(
                        Number(selectedRoomRef.current?.partner_id),
                        data.sender_device_id
                      );
                      if (!peerKey) throw new Error('peer-key-missing');
                      resolvedContent = await decryptFromPeer(
                        String(data.content ?? ''),
                        String(data.nonce ?? ''),
                        peerKey
                      );
                    } catch {
                      resolvedContent = encryptedPlaceholder();
                    }
                  }
                } else if (selectedRoomTypeRef.current === 'group' && selectedRoomRef.current) {
                  try {
                    const keyVersion = Number(data.key_version ?? selectedRoomRef.current.current_key_version ?? 1);
                    const roomKeyB64 = await ensureGroupRoomKey(selectedRoomRef.current, keyVersion);
                    if (!roomKeyB64) {
                      resolvedContent = encryptedPlaceholder();
                    } else {
                      resolvedContent = await decryptFromRoom(
                        String(data.content ?? ''),
                        String(data.nonce ?? ''),
                        roomKeyB64
                      );
                    }
                  } catch {
                    resolvedContent = encryptedPlaceholder();
                  }
                }
                setMyRooms((prev) => {
                  const idx = prev.findIndex((r) => sameId(r.id, data.room_id));
                  if (idx === -1) return prev;
                  const next = [...prev];
                  const target = next[idx];
                  next[idx] = {
                    ...target,
                    last_message: resolvedContent,
                    last_message_sender: data.sender_nickname ?? target.last_message_sender ?? null,
                    updated_at: data.timestamp ?? new Date().toISOString(),
                  };
                  next.sort(
                    (a, b) =>
                      new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
                  );
                  return next;
                });
                setPreviewCache(Number(data.room_id), resolvedContent);
                setMsgList((prev) => {
                  if (prev.some((m) => sameId(m.id, data.id))) return prev;
                  return [...prev, {
                    id: data.id,
                    sender_id: data.sender_id,
                    sender_nickname: nickname,
                    content: resolvedContent,
                    nonce: data.nonce ?? randomNonce(12),
                    key_version: Number(data.key_version ?? 1),
                    room_id: data.room_id,
                    created_at: data.timestamp,
                    is_edited: data.is_edited ?? false,
                    // Для своих новых сообщений ставим одну галку (sent),
                    // двойная появится только после messages_read от собеседника.
                    is_read: false,
                    edited_at: null
                  }];
                });
              })();
              if (!isMe(data.sender_id)) {
                messages.markAsRead(data.room_id).catch(console.error);
              }
            } else {
              void (async () => {
                const targetRoom = myRoomsRef.current.find((r) => sameId(r.id, data.room_id));
                let resolvedPreview = String(data.content ?? '');
                try {
                  if (
                    targetRoom &&
                    targetRoom.type === 'direct' &&
                    targetRoom.partner_id != null &&
                    typeof data.nonce === 'string'
                  ) {
                    const peerKey = await fetchPeerPublicKey(Number(targetRoom.partner_id));
                    if (peerKey) {
                      resolvedPreview = await decryptFromPeer(
                        String(data.content ?? ''),
                        String(data.nonce ?? ''),
                        peerKey
                      );
                      setPreviewCache(Number(data.room_id), resolvedPreview);
                    }
                  }
                } catch {
                  // keep ciphertext fallback for this tick
                }
                setMyRooms((prev) => {
                  const idx = prev.findIndex((r) => sameId(r.id, data.room_id));
                  if (idx === -1) return prev;
                  const next = [...prev];
                  const target = next[idx];
                  next[idx] = {
                    ...target,
                    last_message: resolvedPreview,
                    last_message_sender: data.sender_nickname ?? target.last_message_sender ?? null,
                    updated_at: data.timestamp ?? new Date().toISOString(),
                  };
                  next.sort(
                    (a, b) =>
                      new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
                  );
                  return next;
                });
              })();
              const targetRoom = myRoomsRef.current.find((r) => sameId(r.id, data.room_id));
              const roomTitle = targetRoom
                ? getRoomSidebarTitle(targetRoom)
                : `комната #${data.room_id}`;
              showToast(`Новое сообщение: ${roomTitle}`, 'info');
              loadRooms();
            }
            break;
          case 'message_edited':
            if (sameId(data.room_id, roomOpen)) {
              void (async () => {
                let resolvedContent = String(data.content ?? '');
                if (selectedRoomTypeRef.current === 'direct') {
                  if (!activePeerPublicKeyRef.current) {
                    resolvedContent = encryptedPlaceholder();
                  } else {
                    try {
                      const peerKey = await resolvePeerPublicKey(
                        Number(selectedRoomRef.current?.partner_id),
                        data.sender_device_id
                      );
                      if (!peerKey) throw new Error('peer-key-missing');
                      resolvedContent = await decryptFromPeer(
                        String(data.content ?? ''),
                        String(data.nonce ?? ''),
                        peerKey
                      );
                    } catch {
                      resolvedContent = encryptedPlaceholder();
                    }
                  }
                } else if (selectedRoomTypeRef.current === 'group' && selectedRoomRef.current) {
                  try {
                    const keyVersion = Number(data.key_version ?? selectedRoomRef.current.current_key_version ?? 1);
                    const roomKeyB64 = await ensureGroupRoomKey(selectedRoomRef.current, keyVersion);
                    if (!roomKeyB64) {
                      resolvedContent = encryptedPlaceholder();
                    } else {
                      resolvedContent = await decryptFromRoom(
                        String(data.content ?? ''),
                        String(data.nonce ?? ''),
                        roomKeyB64
                      );
                    }
                  } catch {
                    resolvedContent = encryptedPlaceholder();
                  }
                }
                setMsgList((prev) => prev.map((msg) =>
                  sameId(msg.id, data.id)
                    ? {
                        ...msg,
                        content: resolvedContent,
                        nonce: data.nonce ?? msg.nonce,
                        key_version: Number(data.key_version ?? msg.key_version),
                        is_edited: true,
                        edited_at: data.timestamp,
                      }
                    : msg
                ));
              })();
            }
            break;
          case 'message_deleted':
            if (sameId(data.room_id, roomOpen)) {
              setMsgList((prev) => prev.filter((msg) => !sameId(msg.id, data.id)));
            }
            break;
          case 'new_room':
            loadRooms();
            break;
          case 'direct_room_ready':
            if (data.peer_id != null) {
              void fetchPeerPublicKey(Number(data.peer_id));
              void warmupPeerDevices(Number(data.peer_id));
            }
            loadRooms();
            break;
          case 'messages_read':
            if (
              sameId(data.room_id, roomOpen) &&
              !isMe(data.reader_id)
            ) {
              setMsgList((prev) =>
                prev.map((m) =>
                  isMe(m.sender_id) && Number(m.id) > 0
                    ? { ...m, is_read: true }
                    : m
                )
              );
            }
            break;
        }
      } catch (e) {
        console.error('❌ WebSocket ошибка парсинга:', e);
      }
    };

    ws.current.onclose = () => {
      console.log('❌ WebSocket отключился');
    };
    return () => {
      if (ws.current) {
        ws.current.close();
        ws.current = null;
      }
    };
  }, [userId, isMe, fetchPeerPublicKey, warmupPeerDevices, resolvePeerPublicKey]);

  // Смена комнаты: снова join_room (сокет уже авторизован с сервера)
  useEffect(() => {
    if (!selectedRoom?.id || !userId) return;
    const roomId = selectedRoom.id;
    const sendJoin = () => {
      if (ws.current?.readyState === WebSocket.OPEN) {
        ws.current.send(JSON.stringify({ action: 'join_room', room_id: roomId }));
      }
    };
    sendJoin();
    const sock = ws.current;
    if (sock && sock.readyState === WebSocket.CONNECTING) {
      sock.addEventListener('open', sendJoin, { once: true });
      return () => sock.removeEventListener('open', sendJoin);
    }
    return undefined;
  }, [selectedRoom?.id, userId]);

  // При выборе комнаты — грузим сообщения через REST (не ждем WebSocket)
  useEffect(() => {
    if (!selectedRoom?.id) return;

    setLastCursor(undefined);
    lastCursorRef.current = undefined;
    setHasMoreMessages(true);
    setMsgList([]);
    if (selectedRoom.type === 'group') {
      setGroupHandshakeReady(false);
      setGroupHandshakeBusy(true);
      void ensureGroupRoomKey(selectedRoom, selectedRoom.current_key_version)
        .then((key) => {
          setGroupHandshakeReady(Boolean(key));
          setGroupHandshakeBusy(false);
        })
        .catch((err) => {
          console.error('Не удалось подготовить group room key:', err);
          setGroupHandshakeBusy(false);
        });
    } else {
      setGroupHandshakeReady(false);
      setGroupHandshakeBusy(false);
    }
    void loadMessages(false);
    loadRoomMembers(selectedRoom.id);

    const timer = setTimeout(() => {
      messages.markAsRead(selectedRoom.id);
      loadUnreadCounts();
    }, 1500);

    return () => clearTimeout(timer);
  }, [
    selectedRoom?.id,
    selectedRoom?.type,
    selectedRoom?.current_key_version,
    ensureGroupRoomKey,
  ]);

  // Загрузка сообщений с cursor (API: от старых к новым — как в мессенджере, сверху вниз)
  const loadMessages = useCallback(async (append = false) => {
    if (!selectedRoom) return;
    if (append) setLoadingMore(true);

    try {
      const cursor = append ? lastCursorRef.current : undefined;
      const r = await messages.get(selectedRoom.id, 50, cursor);
      const newMsgs = (r.data.messages || []) as Message[];
      const normalizedMsgs: Message[] = await Promise.all(
        newMsgs.map(async (m) => {
          if (selectedRoom.type === 'direct') {
            if (!activePeerPublicKey) return { ...m, content: encryptedPlaceholder() };
            try {
              const peerKey = await resolvePeerPublicKey(
                Number(selectedRoom.partner_id),
                m.sender_device_id
              );
              if (!peerKey) throw new Error('peer-key-missing');
              const plain = await decryptFromPeer(m.content, m.nonce, peerKey);
              return { ...m, content: plain };
            } catch {
              return { ...m, content: encryptedPlaceholder() };
            }
          }
          if (selectedRoom.type === 'group') {
            try {
              const roomKeyB64 = await ensureGroupRoomKey(selectedRoom, Number(m.key_version ?? selectedRoom.current_key_version ?? 1));
              if (!roomKeyB64) return { ...m, content: encryptedPlaceholder() };
              const plain = await decryptFromRoom(m.content, m.nonce, roomKeyB64);
              return { ...m, content: plain };
            } catch {
              return { ...m, content: encryptedPlaceholder() };
            }
          }
          return m;
        })
      );

      if (append) {
        setMsgList((prev) => [...normalizedMsgs, ...prev]);
      } else {
        setMsgList(normalizedMsgs);
        if (normalizedMsgs.length > 0) {
          const latest = normalizedMsgs[normalizedMsgs.length - 1];
          setPreviewCache(selectedRoom.id, latest.content);
          setMyRooms((prev) =>
            prev.map((room) =>
              room.id === selectedRoom.id
                ? {
                    ...room,
                    last_message: latest.content,
                    last_message_sender: latest.sender_nickname ?? room.last_message_sender ?? null,
                    updated_at: latest.created_at ?? room.updated_at,
                  }
                : room
            )
          );
        }
      }

      setHasMoreMessages(r.data.has_more ?? true);
      setLastCursor(r.data.next_cursor);
      lastCursorRef.current = r.data.next_cursor;
    } catch (e) {
      console.error('Ошибка загрузки сообщений:', e);
    } finally {
      setLoadingMore(false);
    }
  }, [selectedRoom, activePeerPublicKey, ensureGroupRoomKey, resolvePeerPublicKey]);

  // В direct-чате после перезахода ключ собеседника может приехать позже, чем первая загрузка истории.
  // Как только ключ появился — перезагружаем сообщения, чтобы они сразу расшифровались.
  useEffect(() => {
    if (!selectedRoom || selectedRoom.type !== 'direct') return;
    if (!activePeerPublicKey) return;
    void loadMessages(false);
  }, [selectedRoom?.id, selectedRoom?.type, activePeerPublicKey, loadMessages]);

  // Обработка скролла вверх (подгрузка старых сообщений)
  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const element = e.currentTarget;
    // Если скролл вверху (с запасом 50px) и есть еще сообщения
    if (element.scrollTop < 50 && hasMoreMessages && !loadingMore) {
      loadMessages(true);
    }
  };

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ behavior: 'smooth' });
  }, [msgList]);

  // Заголовок чата: из API (partner_*) или из загруженных участников
  const getDirectRoomName = (room: Room): string => {
    if (room.type !== 'direct') return room.name || 'Без названия';
    const fromApi = getRoomSidebarTitle(room);
    const alias = getAlias(room.partner_id);
    if (alias) return alias;
    if (fromApi !== 'Личная переписка') return fromApi;
    const other = roomMembers.find((m) => !isMe(m.id));
    return preferAlias(other?.id, other?.nickname || other?.username || 'Личная переписка');
  };

  const isRoomReadyToSend = useCallback((room: Room): boolean => {
    if (room.type === 'direct') return Boolean(activePeerPublicKey && directHandshakeReady);
    if (room.type === 'group') return Boolean(groupHandshakeReady);
    return true;
  }, [activePeerPublicKey, directHandshakeReady, groupHandshakeReady]);

  const queueMessageToOutbox = useCallback((room: Room, text: string) => {
    const localId = -Date.now();
    const nowIso = new Date().toISOString();
    setPendingOutbox((prev) => [
      ...prev,
      {
        local_id: localId,
        room_id: room.id,
        text,
        created_at: nowIso,
        attempts: 0,
      },
    ]);
    setMsgList((prev) => [
      ...prev,
      {
        id: localId,
        room_id: room.id,
        sender_id: userId!,
        sender_nickname: 'Вы',
        content: `${text}`,
        nonce: randomNonce(12),
        key_version: Number(room.current_key_version ?? 1),
        created_at: nowIso,
        is_edited: false,
        edited_at: null,
        is_read: false,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
      } as any,
    ]);
    setMyRooms((prev) =>
      prev.map((r) =>
        r.id === room.id
          ? { ...r, last_message: text, last_message_sender: 'Вы', updated_at: nowIso }
          : r
      )
    );
    setPreviewCache(room.id, text);
  }, [setPreviewCache, userId]);

  const sendEncryptedText = useCallback(async (room: Room, text: string, localId?: number): Promise<boolean> => {
    const isDirect = room.type === 'direct';
    const encrypted = isDirect
      ? await encryptForPeer(text, activePeerPublicKey as string)
      : await (async () => {
          const keyVersion = Number(room.current_key_version ?? 1);
          const roomKeyB64 = await ensureGroupRoomKey(room, keyVersion);
          if (!roomKeyB64) throw new Error('Не удалось получить room-key для группы');
          return encryptForRoom(text, roomKeyB64, keyVersion);
        })();

    const res = await messages.send({
      room_id: room.id,
      content: encrypted.content,
      nonce: encrypted.nonce,
      key_version: encrypted.key_version,
      sender_device_id: e2e.getDeviceId(),
    });
    const data = res.data as { id: number; content: string; nonce?: string; key_version?: number; timestamp?: string };
    setMsgList((prev) => {
      const filtered = localId != null ? prev.filter((m) => !sameId(m.id, localId)) : prev;
      if (filtered.some((m) => sameId(m.id, data.id))) return filtered;
      return [...filtered, {
        id: data.id,
        room_id: room.id,
        sender_id: userId!,
        sender_nickname: 'Вы',
        content: text,
        nonce: data.nonce ?? encrypted.nonce,
        key_version: Number(data.key_version ?? encrypted.key_version),
        created_at: data.timestamp ?? new Date().toISOString(),
        is_edited: false,
        edited_at: null,
        is_read: false,
      }];
    });
    setMyRooms((prev) =>
      prev.map((r) =>
        r.id === room.id
          ? {
              ...r,
              last_message: text,
              last_message_sender: 'Вы',
              updated_at: data.timestamp ?? new Date().toISOString(),
            }
          : r
      )
    );
    setPreviewCache(room.id, text);
    return true;
  }, [activePeerPublicKey, ensureGroupRoomKey, setPreviewCache, userId]);

  // Отправка сообщения
  const sendMsg = async () => {
    if (!selectedRoom || !input.trim() || isSending || sendCooldown) return;
    const room = selectedRoom;
    const text = input.trim();
    setInput('');
    if (!isRoomReadyToSend(room)) {
      queueMessageToOutbox(room, text);
      showToast('Сообщение добавлено в буфер, отправим после обмена ключами', 'info');
      return;
    }
    setIsSending(true);
    try {
      await sendEncryptedText(room, text);
    } catch (e: unknown) {
      const err = e as { response?: { status?: number } };
      if (err.response?.status === 429) {
        setSendCooldown(true);
        showToast('Слишком много сообщений. Подожди', 'error');
        setTimeout(() => setSendCooldown(false), 20_000);
      } else {
        queueMessageToOutbox(room, text);
        showToast('Ключи еще не готовы, сообщение ушло в буфер', 'info');
      }
    } finally {
      setIsSending(false);
    }
  };

  useEffect(() => {
    if (!selectedRoom) return;
    if (!isRoomReadyToSend(selectedRoom)) return;
    const pendingForRoom = pendingOutboxRef.current.filter((p) => p.room_id === selectedRoom.id);
    if (!pendingForRoom.length) return;
    void (async () => {
      for (const item of pendingForRoom) {
        try {
          await sendEncryptedText(selectedRoom, item.text, item.local_id);
          setPendingOutbox((prev) => prev.filter((p) => p.local_id !== item.local_id));
        } catch {
          setPendingOutbox((prev) =>
            prev.map((p) =>
              p.local_id === item.local_id ? { ...p, attempts: p.attempts + 1 } : p
            )
          );
          break;
        }
      }
    })();
  }, [selectedRoom?.id, isRoomReadyToSend, sendEncryptedText, pendingOutbox]);

  useEffect(() => {
    if (!selectedRoom) return;
    const pendingForRoom = pendingOutbox.filter((p) => p.room_id === selectedRoom.id);
    setMsgList((prev) => {
      const withoutStaleLocal = prev.filter((m) => !(Number(m.id) < 0));
      const pendingAsMessages = pendingForRoom.map((item) => ({
        id: item.local_id,
        room_id: item.room_id,
        sender_id: userId!,
        sender_nickname: 'Вы',
        content: item.text,
        nonce: randomNonce(12),
        key_version: Number(selectedRoom.current_key_version ?? 1),
        created_at: item.created_at,
        is_edited: false,
        edited_at: null,
        is_read: false,
      })) as Message[];
      return [...withoutStaleLocal, ...pendingAsMessages];
    });
  }, [pendingOutbox, selectedRoom?.id, selectedRoom?.current_key_version, userId]);

  const rotateLocalE2EKey = async () => {
    try {
      clearLocalPrivateKey();
      const { publicKeyB64 } = await ensureOwnPublicKey();
      await e2e.upsertPublicKey(publicKeyB64);
      await e2e.upsertDeviceKey(publicKeyB64);
      setHasE2EKey(true);
      showToast('Локальный E2E-ключ обновлен', 'success');
    } catch (err) {
      console.error(err);
      showToast('Не удалось обновить E2E-ключ', 'error');
    }
  };

  const rotateGroupE2EKey = async () => {
    if (!selectedRoom || selectedRoom.type !== 'group') return;
    try {
      const rotateRes = await rooms.rotateRoomKey(selectedRoom.id);
      const newVersion = Number(rotateRes.data.current_key_version);
      const membersRes = await rooms.getMembers(selectedRoom.id);
      const members = (membersRes.data || []) as RoomMember[];
      const roomKeyB64 = generateRoomKey();
      const envelopes = await Promise.all(
        members.map(async (member) => {
          const pk = await e2e.getPublicKey(member.id);
          const encryptedKey = await encryptRoomKeyForMember(roomKeyB64, pk.data.public_key);
          return {
            user_id: member.id,
            encrypted_key: encryptedKey,
            algorithm: 'p256-ecdh-v1',
          };
        })
      );
      await rooms.upsertRoomKeys(selectedRoom.id, {
        key_version: newVersion,
        envelopes,
      });
      putCachedRoomKey(selectedRoom.id, newVersion, roomKeyB64);
      setSelectedRoom((prev) => (prev ? { ...prev, current_key_version: newVersion } : prev));
      setMyRooms((prev) =>
        prev.map((room) =>
          room.id === selectedRoom.id ? { ...room, current_key_version: newVersion } : room
        )
      );
      showToast('Групповой E2E-ключ ротирован', 'success');
    } catch (e: unknown) {
      showToast(apiErrorDetail(e, 'Не удалось выполнить ротацию E2E-ключа'), 'error');
    }
  };

  // Редактирование сообщения
  const editMsg = async (msgId: number, newContent: string) => {
    if (!selectedRoom) return;
    const trimmed = newContent.trim();
    if (!trimmed) {
      showToast('Пустое сообщение', 'error');
      return;
    }
    try {
      const current = msgList.find((m) => sameId(m.id, msgId));
      const isDirect = selectedRoom.type === 'direct';
      if (isDirect && !activePeerPublicKey) {
        showToast('Нет E2E-ключа собеседника', 'error');
        return;
      }
      const encrypted = isDirect
        ? await encryptForPeer(trimmed, activePeerPublicKey as string)
        : await (async () => {
            const keyVersion = Number(current?.key_version ?? selectedRoom.current_key_version ?? 1);
            const roomKeyB64 = await ensureGroupRoomKey(selectedRoom, keyVersion);
            if (!roomKeyB64) throw new Error('Не удалось получить room-key для группы');
            return encryptForRoom(trimmed, roomKeyB64, keyVersion);
          })();
      await messages.edit(Number(msgId), {
        content: encrypted.content,
        nonce: encrypted.nonce,
        key_version: encrypted.key_version,
      });
      const now = new Date().toISOString();
      setMsgList((prev) =>
        prev.map((m) =>
          sameId(m.id, msgId)
            ? {
                ...m,
                content: trimmed,
                nonce: encrypted.nonce,
                key_version: encrypted.key_version,
                is_edited: true,
                edited_at: now,
              }
            : m
        )
      );
      setMyRooms((prev) =>
        prev.map((room) =>
          room.id === selectedRoom.id
            ? {
                ...room,
                last_message: trimmed,
                updated_at: now,
              }
            : room
        )
      );
      setPreviewCache(selectedRoom.id, trimmed);
      setEditingMsg(null);
      showToast('Сообщение отредактировано', 'success');
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      showToast(err.response?.data?.detail || 'Ошибка', 'error');
    }
  };

  // Стейт для контекстного меню (сообщение)
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; msgId: number | string } | null>(null);
  /** ПКМ по строке чата в сайдбаре */
  const [roomContextMenu, setRoomContextMenu] = useState<{ x: number; y: number; room: Room } | null>(null);

  // Удаление сообщения
  const deleteMsg = async (msgId: number | string) => {
    setContextMenu(null);
    if (!selectedRoom) return;
    const idNum = Number(msgId);
    try {
      await messages.delete(idNum);
      setMsgList((prev) => prev.filter((m) => !sameId(m.id, idNum)));
      showToast('Сообщение удалено', 'success');
    } catch (e: unknown) {
      showToast(apiErrorDetail(e, 'Ошибка при удалении'), 'error');
    }
  };

  const removeChatFromSidebar = async (room: Room) => {
    setRoomContextMenu(null);
    try {
      await rooms.deleteSelf(room.id);
      setMyRooms((prev) => prev.filter((r) => r.id !== room.id));
      if (selectedRoom?.id === room.id) {
        setSelectedRoom(null);
        setMsgList([]);
      }
      await loadUnreadCounts();
      showToast('Чат убран из списка', 'success');
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      showToast(err.response?.data?.detail || 'Не удалось удалить чат', 'error');
    }
  };

  /** Очистка только своих сообщений в комнате (у собеседников история не трогается) */
  const clearHistoryForRoom = async (room: Room) => {
    setRoomContextMenu(null);
    try {
      await rooms.clearHistory(room.id);
      showToast('Ваши сообщения в этом чате удалены', 'success');
      if (selectedRoom?.id === room.id) {
        setLastCursor(undefined);
        setHasMoreMessages(true);
        setMsgList([]);
        await loadMessages(false);
      }
      await loadUnreadCounts();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      showToast(err.response?.data?.detail || 'Не удалось очистить историю', 'error');
    }
  };

  const blockPartnerAndRemoveChat = async (room: Room) => {
    if (room.type !== 'direct' || room.partner_id == null) return;
    setRoomContextMenu(null);
    try {
      await friends.block(room.partner_id);
      await rooms.deleteSelf(room.id);
      setMyRooms((prev) => prev.filter((r) => r.id !== room.id));
      if (selectedRoom?.id === room.id) {
        setSelectedRoom(null);
        setMsgList([]);
      }
      await loadFriendsData();
      await loadUnreadCounts();
      showToast('Пользователь заблокирован, чат скрыт', 'success');
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      showToast(err.response?.data?.detail || 'Ошибка блокировки', 'error');
    }
  };

  // Открытие контекстного меню
  const handleContextMenu = (e: React.MouseEvent, msgId: number | string) => {
    e.preventDefault();
    setRoomContextMenu(null);
    setShowRoomMenu(false);
    setContextMenu({ x: e.clientX, y: e.clientY, msgId });
  };

  // Закрытие всех всплывающих меню при mousedown/touchstart вне их (и по Escape)
  useEffect(() => {
    const onPointerDown = (e: MouseEvent | TouchEvent) => {
      const el = e.target instanceof Node ? e.target : null;
      if (!el) return;

      if (!msgContextMenuRef.current?.contains(el)) setContextMenu(null);
      if (!roomSidebarContextMenuRef.current?.contains(el)) setRoomContextMenu(null);
      if (
        !profileMenuRef.current?.contains(el) &&
        !profileButtonRef.current?.contains(el)
      ) {
        setShowProfileMenu(false);
      }

      const inHeaderToolbar =
        roomHeaderActionsRef.current?.contains(el) ||
        roomHeaderDropdownRef.current?.contains(el);
      if (!inHeaderToolbar) setShowRoomMenu(false);
    };

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setContextMenu(null);
        setRoomContextMenu(null);
        setShowRoomMenu(false);
        setShowProfileMenu(false);
        // Быстрый выход в главное меню (без выбранного чата)
        if (selectedRoomIdRef.current != null) {
          setSelectedRoom(null);
          setMsgList([]);
        }
      }
    };

    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('touchstart', onPointerDown, { passive: true });
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('touchstart', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, []);

  // Управление пользователями
  const toggleUserSelection = (uid: number) => {
    setSelectedUsers(prev => prev.includes(uid) ? prev.filter(id => id !== uid) : [...prev, uid]);
  };

  const createRoom = async () => {
    if (!newRoomName.trim()) { showToast('Введите название', 'error'); return; }
    try {
      await rooms.createGroup(newRoomName.trim(), selectedUsers);
      showToast('Комната создана!', 'success');
      setNewRoomName(''); setSelectedUsers([]); setShowCreateRoom(false);
      loadRooms();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      showToast(err.response?.data?.detail || 'Ошибка', 'error');
    }
  };

  const inviteUser = async () => {
    if (!selectedRoom || !inviteUserId) return;
    try {
      await rooms.invite(selectedRoom.id, parseInt(inviteUserId));
      showToast('Пользователь приглашён!', 'success');
      setShowInviteModal(false); setInviteUserId('');
      loadRoomMembers(selectedRoom.id);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      showToast(err.response?.data?.detail || 'Ошибка', 'error');
    }
  };

  const kickUser = async (kickUserId: number) => {
    if (!selectedRoom) return;
    try {
      await rooms.kick(selectedRoom.id, kickUserId);
      showToast('Пользователь кикнут', 'success');
      loadRoomMembers(selectedRoom.id);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      showToast(err.response?.data?.detail || 'Ошибка', 'error');
    }
  };

  const leaveRoom = async () => {
    if (!selectedRoom) return;
    try {
      await rooms.leave(selectedRoom.id);
      showToast('Вы вышли из комнаты', 'success');
      setSelectedRoom(null);
      loadRooms();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      showToast(err.response?.data?.detail || 'Ошибка', 'error');
    }
  };

  const addFriend = async () => {
    if (!friendUsername.trim()) return;
    try {
      await friends.sendRequest(friendUsername.trim());
      showToast('Заявка отправлена!', 'success');
      setFriendUsername('');
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      showToast(err.response?.data?.detail || 'Ошибка', 'error');
    }
  };

  const acceptFriendRequest = async (friendId: number) => {
    try { await friends.accept(friendId); loadFriendsData(); } catch (e) { console.error(e); }
  };

  const declineFriendRequest = async (friendId: number) => {
    try { await friends.decline(friendId); loadFriendsData(); } catch (e) { console.error(e); }
  };

  const openDirectChat = async (friendId: number) => {
    try {
      const r = await rooms.createDirect(friendId);
      const createdRoom = r.data;
      setMyRooms(prev => !prev.some(room => room.id === createdRoom.id) ? [...prev, createdRoom] : prev);
      setSelectedRoom(createdRoom);
      setActiveMenu('chats');
      showToast('Чат открыт!', 'success');
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      showToast(err.response?.data?.detail || 'Не удалось создать чат', 'error');
    }
  };

  const filteredRooms = [...myRooms]
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
    .filter((room) => {
      const query = searchInput.toLowerCase().trim();
      if (!query) return true;
      const title = getRoomSidebarTitle(room).toLowerCase();
      const preview = getRoomPreview(room).toLowerCase();
      return title.includes(query) || preview.includes(query);
    });

  const isOwner = selectedRoom && isMe(selectedRoom.created_by);
  const profileLabel = profileNickname || (userId != null ? `User #${userId}` : 'Профиль');
  const profileUsernameLabel = profileUsername ? `@${profileUsername}` : '@unknown';
  const profileInitial = profileLabel[0]?.toUpperCase() || 'U';

  const copyProfileUsername = async () => {
    if (!profileUsername) return;
    try {
      await navigator.clipboard.writeText(`@${profileUsername}`);
      showToast('Username скопирован', 'success');
    } catch {
      showToast('Не удалось скопировать username', 'error');
    }
  };

  return (
    <div className="chat-page">
      {/* Левый мини-сайдбар */}
      <div className="left-sidebar">
        <div className="server-icon active" title="MsgHub">M</div>
        <div className="separator"></div>
        <button className={`nav-btn ${activeMenu === 'chats' ? 'active' : ''}`} onClick={() => setActiveMenu('chats')} title="Чаты">💬</button>
        <button className={`nav-btn ${activeMenu === 'friends' ? 'active' : ''}`} onClick={() => setActiveMenu('friends')} title="Друзья">👥</button>
        <button className={`nav-btn ${activeMenu === 'requests' ? 'active' : ''}`} onClick={() => { setActiveMenu('requests'); loadFriendsData(); }} title="Заявки">
          🔔{friendRequests.length > 0 && <span className="badge">{friendRequests.length}</span>}
        </button>
        <div className="spacer"></div>
        <button className={`nav-btn ${activeMenu === 'settings' ? 'active' : ''}`} onClick={() => setActiveMenu('settings')} title="Настройки">⚙️</button>
        <button className="nav-btn logout-nav-btn" onClick={logout} title="Выйти">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline d="M16 17l5-5-5-5"/><line x1="21" y1="12" x2="9" y2="12"/>
          </svg>
        </button>
      </div>

      {/* Средний сайдбар */}
      <div className="middle-sidebar">
        <div className="sidebar-header">
          <button
            ref={profileButtonRef}
            className="profile-widget"
            onClick={() => setShowProfileMenu((v) => !v)}
            title="Профиль и настройки"
          >
            <span className="profile-widget-avatar">{profileInitial}</span>
            <span className="profile-widget-meta">
              <span className="profile-widget-name">{profileLabel}</span>
              <button
                type="button"
                className="profile-widget-subname profile-username-copy"
                onClick={(e) => {
                  e.stopPropagation();
                  void copyProfileUsername();
                }}
                title="Скопировать @username"
              >
                {profileUsernameLabel}
              </button>
            </span>
          </button>
          {showProfileMenu && (
            <div className="profile-menu" ref={profileMenuRef}>
              <button onClick={() => { setActiveMenu('settings'); setShowProfileMenu(false); }}>
                ⚙️ Профиль и настройки
              </button>
              <button onClick={() => { setActiveMenu('settings'); setShowProfileMenu(false); }}>
                🖥️ Настройки приложения (скоро)
              </button>
              <button className="danger" onClick={logout}>
                ⎋ Выйти
              </button>
            </div>
          )}
        </div>
        <div className="search-box">
          <input type="text" placeholder="Поиск..." value={searchInput} onChange={(e) => setSearchInput(e.target.value)} className="search-input" />
        </div>

        {activeMenu === 'chats' && (
          <div className="content-panel">
            <div className="panel-header">
              <h3>Чаты</h3>
              <button className="create-room-btn" onClick={() => setShowCreateRoom(true)} title="Создать комнату">+</button>
            </div>
            <div className="room-list">
              {filteredRooms.map((room) => {
                const unread = unreadCounts[room.id] || 0;
                const roomTitle = room.type === 'direct' && room.partner_id != null
                  ? (getAlias(room.partner_id) || getRoomSidebarTitle(room))
                  : getRoomSidebarTitle(room);
                const roomPreview = getRoomPreview(room);
                return (
                <div
                  key={room.id}
                  className={`room-item ${selectedRoom?.id === room.id ? 'selected' : ''}`}
                  onClick={() => {
                    setSelectedRoom(room);
                    loadUnreadCounts();
                  }}
                  onContextMenu={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    setContextMenu(null);
                    setShowRoomMenu(false);
                    setRoomContextMenu({ x: e.clientX, y: e.clientY, room });
                  }}
                >
                  <span className="room-icon">{room.type === 'direct' ? '👤' : '#'}</span>
                  <div className="room-text">
                    <span className="room-name">{roomTitle}</span>
                    <span className="room-preview">{roomPreview}</span>
                  </div>
                  {unread > 0 && <span className="unread-badge">{unread > 99 ? '99+' : unread}</span>}
                </div>
              )})}
              {filteredRooms.length === 0 && <p className="empty">Нет чатов</p>}
            </div>
          </div>
        )}

        {activeMenu === 'friends' && (
          <div className="content-panel">
            <div className="add-friend-section">
              <label>Добавить друга</label>
              <div className="add-friend-input">
                <input type="text" placeholder="Username" value={friendUsername} onChange={(e) => setFriendUsername(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && addFriend()} />
                <button onClick={addFriend} className="add-btn">+</button>
              </div>
            </div>
            <div className="friends-section">
              <h4>Друзья ({friendList.length})</h4>
              {friendList.length > 0 ? (
                <div className="friend-list">
                  {friendList.map((f) => (
                    <div key={f.id} className="friend-item">
                      <div className="friend-info">
                        <span className="friend-name">{f.nickname || f.username}</span>
                        <span className={`friend-status ${f.is_online ? 'online' : 'offline'}`}>
                          {f.is_online ? 'online' : 'offline'}
                        </span>
                      </div>
                      <button className="msg-btn" onClick={() => openDirectChat(f.id)}>💬</button>
                    </div>
                  ))}
                </div>
              ) : <p className="empty-section">Нет друзей</p>}
            </div>
          </div>
        )}

        {activeMenu === 'requests' && (
          <div className="content-panel">
            <div className="requests-section">
              <h4>Заявки ({friendRequests.length})</h4>
              {friendRequests.length > 0 ? (
                <div className="request-list">
                  {friendRequests.map((req) => {
                    const displayName = req.nickname || req.username || `Пользователь #${req.partner_id || req.sender_id}`;
                    return (
                      <div key={req.id} className="request-item">
                        <div className="request-info">
                          <span className="request-name">{displayName}</span>
                          <span className="request-status pending">{isMe(req.sender_id) ? 'Ожидает ответа' : 'Хочет добавить вас'}</span>
                        </div>
                        <div className="request-actions">
                          {!isMe(req.sender_id) && <button className="accept-btn" onClick={() => acceptFriendRequest(req.id)}>✓</button>}
                          <button className="decline-btn" onClick={() => declineFriendRequest(req.id)}>✕</button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : <p className="empty-section">Нет заявок</p>}
            </div>
          </div>
        )}

        {activeMenu === 'settings' && (
          <div className="content-panel settings-panel">
            <div className="settings-section">
              <h4>Профиль</h4>
              <div className="setting-item">
                <input
                  placeholder="Никнейм"
                  value={profileDraft.nickname}
                  onChange={(e) => setProfileDraft((p) => ({ ...p, nickname: e.target.value }))}
                />
              </div>
              <div className="setting-item">
                <input
                  placeholder="Email"
                  value={profileDraft.email}
                  onChange={(e) => setProfileDraft((p) => ({ ...p, email: e.target.value }))}
                />
              </div>
              <div className="setting-item">
                <input
                  placeholder="Статус"
                  value={profileDraft.status_message}
                  onChange={(e) => setProfileDraft((p) => ({ ...p, status_message: e.target.value }))}
                />
              </div>
              <div className="setting-item">
                <input
                  placeholder="Тег профиля"
                  value={profileDraft.profile_tag}
                  onChange={(e) => setProfileDraft((p) => ({ ...p, profile_tag: e.target.value }))}
                />
              </div>
              <button
                className="btn-secondary"
                onClick={async () => {
                  try {
                    await auth.updateMe(profileDraft);
                    showToast('Профиль обновлен', 'success');
                  } catch (e) {
                    showToast(apiErrorDetail(e, 'Не удалось обновить профиль'), 'error');
                  }
                }}
              >
                Сохранить профиль
              </button>
              <div className="setting-item">
                <span className="setting-label">ID пользователя</span>
                <span className="setting-value">#{userId}</span>
              </div>
              <div className="setting-item">
                <span className="setting-label">Комнат</span>
                <span className="setting-value">{myRooms.length}</span>
              </div>
              <div className="setting-item">
                <span className="setting-label">Друзей</span>
                <span className="setting-value">{friendList.length}</span>
              </div>
              <div className="setting-item">
                <span className="setting-label">E2E локальный ключ</span>
                <span className="setting-value">{hasE2EKey ? 'Есть' : 'Нет'}</span>
              </div>
              <button className="btn-secondary" onClick={rotateLocalE2EKey}>
                Обновить локальный E2E-ключ
              </button>
              <h4 style={{ marginTop: 16 }}>Сессии</h4>
              {sessions.map((s) => (
                <div key={s.id} className="setting-item">
                  <span className="setting-label">{s.device_info || 'Unknown device'} ({s.ip_address || 'n/a'})</span>
                  <button
                    className="btn-secondary"
                    onClick={async () => {
                      try {
                        await auth.revokeSession(s.id);
                        setSessions((prev) => prev.filter((x) => x.id !== s.id));
                      } catch {
                        showToast('Не удалось завершить сессию', 'error');
                      }
                    }}
                  >
                    Завершить
                  </button>
                </div>
              ))}
              <button
                className="btn-secondary"
                onClick={async () => {
                  try {
                    await auth.revokeOthers();
                    const r = await auth.getSessions();
                    setSessions(r.data.sessions || []);
                    showToast('Осталась только текущая сессия', 'success');
                  } catch {
                    showToast('Не удалось завершить остальные сессии', 'error');
                  }
                }}
              >
                Завершить остальные сессии
              </button>
            </div>
            {isAdmin && (
              <div className="settings-section">
                <h4>Админ-панель (MVP)</h4>
                {adminUsers.map((u) => (
                  <div className="setting-item" key={u.id}>
                    <span className="setting-label">#{u.id} {u.nickname} (@{u.username})</span>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <button className="btn-secondary" onClick={() => auth.adminGrant(u.id)}>+admin</button>
                      <button className="btn-secondary" onClick={() => auth.adminRevoke(u.id)}>-admin</button>
                      <button className="btn-secondary" onClick={() => auth.adminBan(u.id)}>ban</button>
                      <button className="btn-secondary" onClick={() => auth.adminUnban(u.id)}>unban</button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className="settings-section app-settings-placeholder">
              <h4>Настройки приложения (задел под Electron)</h4>
              <div className="setting-item">
                <span className="setting-label">Тема интерфейса</span>
                <span className="setting-value">Скоро</span>
              </div>
              <div className="setting-item">
                <span className="setting-label">Горячие клавиши</span>
                <span className="setting-value">Скоро</span>
              </div>
              <div className="setting-item">
                <span className="setting-label">Уведомления</span>
                <span className="setting-value">Скоро</span>
              </div>
            </div>
            <button className="logout-btn-full" onClick={logout}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline d="M16 17l5-5-5-5"/><line x1="21" y1="12" x2="9" y2="12"/>
              </svg>
              Выйти из аккаунта
            </button>
          </div>
        )}
      </div>

      {/* Правая часть — чат */}
      <div className="main-chat">
        {selectedRoom ? (
          <>
            <div className="chat-header">
              <div className="header-left">
                <span className="chat-icon">{selectedRoom.type === 'direct' ? '👤' : '#'}</span>
                <div className="header-info">
                  <h3>{selectedRoom.type === 'direct' ? getDirectRoomName(selectedRoom) : selectedRoom.name}</h3>
                  <p className="chat-subtitle">
                    {selectedRoom.type === 'direct'
                      ? (selectedRoom.partner_username
                          ? `@${selectedRoom.partner_username}`
                          : 'Личная переписка')
                      : `${roomMembers.length} участников`}
                  </p>
                </div>
              </div>
              <div className="header-right" ref={roomHeaderActionsRef}>
                {selectedRoom.type === 'group' && (
                  <button className="header-btn" onClick={() => setShowRoomMenu(!showRoomMenu)} title="Управление комнатой">⚙️</button>
                )}
                <button className="header-btn" onClick={() => setShowRoomMenu(!showRoomMenu)} title="Опции">⋮</button>
              </div>
            </div>

            {/* Меню управления комнатой */}
            {showRoomMenu && (
              <div className="room-menu" ref={roomHeaderDropdownRef}>
                {selectedRoom.type === 'group' && (
                  <>
                    {isOwner && (
                      <button className="room-menu-item" onClick={async () => {
                        await rotateGroupE2EKey();
                        setShowRoomMenu(false);
                      }}>
                        🔐 Ротация E2E-ключа группы
                      </button>
                    )}
                    <button className="room-menu-item danger" onClick={async () => {
                      await leaveRoom();
                      setShowRoomMenu(false);
                    }}>
                      🚪 Покинуть группу
                    </button>
                    {isOwner && (
                      <button className="room-menu-item" onClick={() => { setShowInviteModal(true); setShowRoomMenu(false); }}>
                        ➕ Пригласить пользователя
                      </button>
                    )}
                  </>
                )}
                
                {selectedRoom.type === 'direct' && (
                  <>
                    <button
                      className="room-menu-item"
                      onClick={() => {
                        const partnerId = selectedRoom.partner_id;
                        if (!partnerId) return;
                        const current = getAlias(partnerId) || '';
                        const nextAlias = window.prompt('Локальный псевдоним для пользователя', current);
                        if (nextAlias == null) return;
                        setLocalAlias(partnerId, nextAlias);
                        showToast('Локальный псевдоним сохранен', 'success');
                        setMyRooms((prev) => [...prev]);
                        setShowRoomMenu(false);
                      }}
                    >
                      📝 Локальный псевдоним
                    </button>
                    <button className="room-menu-item" onClick={async () => {
                      await rooms.clearHistory(selectedRoom.id);
                      setMsgList([]);
                      showToast('История очищена', 'success');
                      setShowRoomMenu(false);
                    }}>
                      🗑 Очистить историю
                    </button>
                    <button className="room-menu-item danger" onClick={async () => {
                      await rooms.deleteSelf(selectedRoom.id);
                      setSelectedRoom(null);
                      loadRooms();
                      showToast('Чат удален', 'success');
                      setShowRoomMenu(false);
                    }}>
                      ❌ Удалить чат
                    </button>
                    <button className="room-menu-item danger" onClick={async () => {
                      const other = roomMembers.find((m) => !isMe(m.id));
                      if (other) {
                        await rooms.ban(selectedRoom.id, other.id);
                        showToast('Пользователь заблокирован', 'success');
                        setShowRoomMenu(false);
                      }
                    }}>
                      🚫 Заблокировать
                    </button>
                  </>
                )}

                {selectedRoom.type === 'group' && isOwner && roomMembers.length > 1 && (
                  <>
                    <div className="room-menu-divider"></div>
                    <p className="room-menu-title">Участники</p>
                    {roomMembers.map(member => (
                      <div key={member.id} className="room-menu-member">
                        <span>{member.nickname || member.username}</span>
                        {!isMe(member.id) && (
                          <button className="kick-btn" onClick={() => kickUser(member.id)}>✕</button>
                        )}
                      </div>
                    ))}
                  </>
                )}
              </div>
            )}

            <div className="messages-list" ref={messagesListRef} onScroll={handleScroll}>
              {loadingMore && <div className="loading-indicator">Загрузка старых сообщений...</div>}
              
              {msgList.map((msg) => (
                <div key={msg.id} className={`message-container ${isMe(msg.sender_id) ? 'own' : ''}`}>
                  <div className="message-avatar">👤</div>
                  <div className="message">
                    <div className="msg-header">
                      <span className="msg-author">
                        {isMe(msg.sender_id)
                          ? 'Вы'
                          : preferAlias(Number(msg.sender_id), msg.sender_nickname || `User #${msg.sender_id}`)}
                      </span>
                      <span className="msg-time">
                        {new Date(msg.created_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}
                        {msg.is_edited && <span className="edited-badge"> (ред.)</span>}
                      </span>
                    </div>
                    {editingMsg && sameId(editingMsg.id, msg.id) ? (
                      <div className="edit-input">
                        <input
                          key={msg.id}
                          type="text"
                          defaultValue={msg.content}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              e.preventDefault();
                              editMsg(msg.id, (e.target as HTMLInputElement).value);
                            }
                            if (e.key === 'Escape') setEditingMsg(null);
                          }}
                          autoFocus
                        />
                        <div className="edit-actions">
                          <button
                            type="button"
                            className="edit-save"
                            onClick={(e) => {
                              const input = (e.currentTarget.closest('.edit-input')?.querySelector('input') as HTMLInputElement) || null;
                              if (input) editMsg(msg.id, input.value);
                            }}
                          >
                            Сохранить
                          </button>
                          <button type="button" className="edit-cancel" onClick={() => setEditingMsg(null)}>
                            Отмена
                          </button>
                        </div>
                        <span className="edit-hint">Enter — сохранить, Esc — отмена</span>
                      </div>
                    ) : (
                      <div 
                        className="msg-content" 
                        title={isMe(msg.sender_id) ? 'Двойной клик — редактировать · ПКМ — меню' : undefined}
                        onContextMenu={(e) => isMe(msg.sender_id) && handleContextMenu(e, msg.id)}
                        onDoubleClick={() => isMe(msg.sender_id) && setEditingMsg(msg)}
                      >
                        <span className="msg-text">
                          {msg.id < 0 ? `${msg.content} ⏳` : msg.content}
                        </span>
                        {/* Бейдж прочтения для своих сообщений */}
                        {isMe(msg.sender_id) && Number(msg.id) > 0 && (
                          <span className={`read-badge ${msg.is_read ? 'read' : 'sent'}`}>
                            {msg.is_read ? '✓✓' : '✓'}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {msgList.length === 0 && <p className="empty-chat">Нет сообщений. Напишите первое!</p>}
              <div ref={messagesEnd} />
            </div>

            {/* Контекстное меню: только свои сообщения (ПКМ) */}
            {contextMenu && (
              <div
                ref={msgContextMenuRef}
                className="msg-context-menu"
                style={{ left: contextMenu.x, top: contextMenu.y }}
                onClick={(e) => e.stopPropagation()}
                onMouseDown={(e) => e.stopPropagation()}
              >
                <button
                  type="button"
                  onClick={() => {
                    const m = msgList.find((x) => sameId(x.id, contextMenu.msgId));
                    setContextMenu(null);
                    if (m) setEditingMsg(m);
                  }}
                >
                  ✏️ Редактировать
                </button>
                <button
                  type="button"
                  className="danger"
                  onClick={() => deleteMsg(contextMenu.msgId)}
                >
                  🗑️ Удалить
                </button>
              </div>
            )}

            <div className="message-input">
              {selectedRoom.type === 'direct' && !directHandshakeReady && (
                <div style={{ color: '#f6c26a', fontSize: 12, paddingBottom: 6 }}>
                  {directHandshakeBusy
                    ? 'Подготовка защищенного канала...'
                    : 'Ожидание обмена ключами...'}
                </div>
              )}
              {selectedRoom.type === 'group' && !groupHandshakeReady && (
                <div style={{ color: '#f6c26a', fontSize: 12, paddingBottom: 6 }}>
                  {groupHandshakeBusy
                    ? 'Подготовка ключа группы...'
                    : 'Ожидание ключа группы...'}
                </div>
              )}
              <input
                type="text"
                placeholder="Написать сообщение..."
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && sendMsg()}
                disabled={
                  (selectedRoom.type === 'direct' && !directHandshakeReady) ||
                  (selectedRoom.type === 'group' && !groupHandshakeReady)
                }
              />
              <button
                onClick={sendMsg}
                className="send-btn"
                disabled={
                  isSending ||
                  sendCooldown ||
                  !input.trim() ||
                  (selectedRoom.type === 'direct' && !directHandshakeReady) ||
                  (selectedRoom.type === 'group' && !groupHandshakeReady)
                }
                title={sendCooldown ? 'Подожди 20 сек...' : 'Отправить'}
              >
                {isSending ? '⏳' : '➤'}
              </button>
            </div>
          </>
        ) : (
          <div className="no-chat">
            <div className="no-chat-content">
              <div className="no-chat-icon">💬</div>
              <h1>Добро пожаловать в MsgHub</h1>
              <p>Выберите чат или создайте новый для начала общения</p>
              <div className="welcome-actions">
                <button onClick={() => setActiveMenu('chats')} className="action-btn">Выбрать чат</button>
                <button onClick={() => setShowCreateRoom(true)} className="action-btn secondary">Создать комнату</button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ПКМ по чату в списке слева — вне main-chat, чтобы работало без открытого чата */}
      {roomContextMenu && (
        <div
          ref={roomSidebarContextMenuRef}
          className="msg-context-menu room-sidebar-context-menu"
          style={{ left: roomContextMenu.x, top: roomContextMenu.y }}
          onClick={(e) => e.stopPropagation()}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            onClick={() => clearHistoryForRoom(roomContextMenu.room)}
            title="Удаляются только ваши сообщения; у других участников переписка сохраняется"
          >
            🧹 Очистить мою историю
          </button>
          <button
            type="button"
            onClick={() => removeChatFromSidebar(roomContextMenu.room)}
          >
            🗑 Удалить чат из списка
          </button>
          {roomContextMenu.room.type === 'direct' && roomContextMenu.room.partner_id != null && (
            <button
              type="button"
              className="danger"
              onClick={() => blockPartnerAndRemoveChat(roomContextMenu.room)}
            >
              🚫 Заблокировать пользователя
            </button>
          )}
        </div>
      )}

      {/* Модалка создания комнаты */}
      {showCreateRoom && (
        <div className="modal-overlay" onClick={() => setShowCreateRoom(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Создать комнату</h2>
              <button className="modal-close" onClick={() => setShowCreateRoom(false)}>✕</button>
            </div>
            <div className="modal-body">
              <div className="form-group">
                <label>Название комнаты</label>
                <input type="text" placeholder="Моя крутая комната" value={newRoomName} onChange={(e) => setNewRoomName(e.target.value)} maxLength={50} autoFocus />
              </div>
              <div className="form-group">
                <label>Пригласить друзей</label>
                <div className="user-select-list">
                  {friendList.length > 0 ? friendList.map(friend => (
                    <div key={friend.id} className={`user-item ${selectedUsers.includes(friend.id) ? 'selected' : ''}`} onClick={() => toggleUserSelection(friend.id)}>
                      <span className="user-avatar">{friend.nickname[0]?.toUpperCase() || '👤'}</span>
                      <span className="user-name">{friend.nickname || friend.username}</span>
                      <span className={`user-check ${selectedUsers.includes(friend.id) ? 'checked' : ''}`}>{selectedUsers.includes(friend.id) ? '✓' : '+'}</span>
                    </div>
                  )) : <p className="empty-hint">Нет друзей для приглашения</p>}
                </div>
              </div>
              {selectedUsers.length > 0 && <div className="selected-count">Выбрано: {selectedUsers.length} {selectedUsers.length === 1 ? 'друг' : 'друзей'}</div>}
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setShowCreateRoom(false)}>Отмена</button>
              <button className="btn-primary" onClick={createRoom}>Создать</button>
            </div>
          </div>
        </div>
      )}

      {/* Модалка приглашения */}
      {showInviteModal && (
        <div className="modal-overlay" onClick={() => setShowInviteModal(false)}>
          <div className="modal modal-sm" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Пригласить пользователя</h2>
              <button className="modal-close" onClick={() => setShowInviteModal(false)}>✕</button>
            </div>
            <div className="modal-body">
              <div className="form-group">
                <label>ID пользователя</label>
                <input type="number" placeholder="Введите ID" value={inviteUserId} onChange={(e) => setInviteUserId(e.target.value)} autoFocus />
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setShowInviteModal(false)}>Отмена</button>
              <button className="btn-primary" onClick={inviteUser}>Пригласить</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
