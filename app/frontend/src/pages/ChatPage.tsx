import { useState, useEffect, useRef, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { rooms, messages, friends, getRoomSidebarTitle, type Room, type Message } from '../services/api';
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

export default function ChatPage() {
  const { userId, logout } = useAuth();
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
  const messagesListRef = useRef<HTMLDivElement>(null);

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

  const messagesEnd = useRef<HTMLDivElement>(null);
  /** Закрытие меню по клику снаружи (см. useEffect ниже) */
  const msgContextMenuRef = useRef<HTMLDivElement>(null);
  const roomSidebarContextMenuRef = useRef<HTMLDivElement>(null);
  const roomHeaderActionsRef = useRef<HTMLDivElement>(null);
  const roomHeaderDropdownRef = useRef<HTMLDivElement>(null);
  const ws = useRef<WebSocket | null>(null);
  /** Актуальная комната для обработчиков WebSocket (иначе замыкание на старый selectedRoom). */
  const selectedRoomIdRef = useRef<number | null>(null);
  useEffect(() => {
    selectedRoomIdRef.current = selectedRoom?.id ?? null;
  }, [selectedRoom?.id]);

  // Загрузка данных
  const loadRooms = async () => {
    try {
      const r = await rooms.getMyRooms();
      setMyRooms(r.data);
    } catch (e) {
      console.error('Ошибка загрузки комнат:', e);
    }
  };

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
  }, []);

  const WS_URL = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000/ws';

  // WebSocket подключение
  useEffect(() => {
    if (!userId) return;
    const token = localStorage.getItem('access_token');
    if (!token) {
      console.error("❌ Нет токена в localStorage, WebSocket не подключится");
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
              setMsgList((prev) => {
                if (prev.some((m) => sameId(m.id, data.id))) return prev;
                return [...prev, {
                  id: data.id,
                  sender_id: data.sender_id,
                  sender_nickname: nickname,
                  content: data.content,
                  room_id: data.room_id,
                  created_at: data.timestamp,
                  is_edited: data.is_edited ?? false,
                  is_read: isMe(data.sender_id),
                  edited_at: null
                }];
              });
              if (!isMe(data.sender_id)) {
                messages.markAsRead(data.room_id).catch(console.error);
              }
            } else {
              showToast(`Новое сообщение в комнате #${data.room_id}`, 'info');
              loadRooms();
            }
            break;
          case 'message_edited':
            if (sameId(data.room_id, roomOpen)) {
              setMsgList((prev) => prev.map((msg) =>
                sameId(msg.id, data.id) ? { ...msg, content: data.content, is_edited: true, edited_at: data.timestamp } : msg
              ));
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
          case 'messages_read':
            if (
              sameId(data.room_id, roomOpen) &&
              !isMe(data.reader_id)
            ) {
              setMsgList((prev) =>
                prev.map((m) =>
                  isMe(m.sender_id) ? { ...m, is_read: true } : m
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
  }, [userId, isMe]);

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
    if (!selectedRoom) return;

    setLastCursor(undefined);
    setHasMoreMessages(true);
    setMsgList([]);
    loadMessages(false);
    loadRoomMembers(selectedRoom.id);

    const timer = setTimeout(() => {
      messages.markAsRead(selectedRoom.id);
      loadUnreadCounts();
    }, 1500);

    return () => clearTimeout(timer);
  }, [selectedRoom]);

  // Загрузка сообщений с cursor (API: от старых к новым — как в мессенджере, сверху вниз)
  const loadMessages = useCallback(async (append = false) => {
    if (!selectedRoom) return;
    if (append) setLoadingMore(true);

    try {
      const cursor = append ? lastCursor : undefined;
      const r = await messages.get(selectedRoom.id, 50, cursor);
      const newMsgs = r.data.messages || [];

      if (append) {
        setMsgList((prev) => [...newMsgs, ...prev]);
      } else {
        setMsgList(newMsgs);
      }

      setHasMoreMessages(r.data.has_more ?? true);
      setLastCursor(r.data.next_cursor);
    } catch (e) {
      console.error('Ошибка загрузки сообщений:', e);
    } finally {
      setLoadingMore(false);
    }
  }, [selectedRoom, lastCursor]);

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
    if (fromApi !== 'Личная переписка') return fromApi;
    const other = roomMembers.find((m) => !isMe(m.id));
    return other?.nickname || other?.username || 'Личная переписка';
  };

  // Отправка сообщения
  const sendMsg = async () => {
    if (!selectedRoom || !input.trim() || isSending || sendCooldown) return;
    setIsSending(true);
    const text = input.trim();
    try {
      const res = await messages.send(selectedRoom.id, text);
      setInput('');
      const data = res.data as { id: number; content: string; timestamp?: string };
      setMsgList((prev) => {
        if (prev.some((m) => sameId(m.id, data.id))) return prev;
        return [...prev, {
          id: data.id,
          room_id: selectedRoom.id,
          sender_id: userId!,
          sender_nickname: 'Вы',
          content: data.content,
          created_at: data.timestamp ?? new Date().toISOString(),
          is_edited: false,
          edited_at: null,
          is_read: false,
        }];
      });
    } catch (e: unknown) {
      const err = e as { response?: { status?: number; data?: { detail?: string } } };
      if (err.response?.status === 429) {
        // Rate limit — блокируем кнопку на 20 секунд
        setSendCooldown(true);
        showToast('Слишком много сообщений. Подожди', 'error');
        setTimeout(() => setSendCooldown(false), 20_000);
      } else {
        console.error(e);
      }
    } finally {
      setIsSending(false);
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
      await messages.edit(Number(msgId), trimmed);
      const now = new Date().toISOString();
      setMsgList((prev) =>
        prev.map((m) =>
          sameId(m.id, msgId)
            ? { ...m, content: trimmed, is_edited: true, edited_at: now }
            : m
        )
      );
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

  const filteredRooms = myRooms.filter((room) =>
    getRoomSidebarTitle(room).toLowerCase().includes(searchInput.toLowerCase())
  );

  const isOwner = selectedRoom && isMe(selectedRoom.created_by);

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
          <h2>MsgHub</h2>
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
                  <span className="room-name">{getRoomSidebarTitle(room)}</span>
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
              <h4>Аккаунт</h4>
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
                      <span className="msg-author">{isMe(msg.sender_id) ? 'Вы' : (msg.sender_nickname || `User #${msg.sender_id}`)}</span>
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
                        <span className="msg-text">{msg.content}</span>
                        {/* Бейдж прочтения для своих сообщений */}
                        {isMe(msg.sender_id) && (
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
              <input
                type="text"
                placeholder="Написать сообщение..."
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && sendMsg()}
              />
              <button
                onClick={sendMsg}
                className="send-btn"
                disabled={isSending || sendCooldown || !input.trim()}
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
