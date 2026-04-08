import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import type { ReactNode } from 'react';
import { auth, setAccessToken } from '../services/api';

interface AuthContextType {
  userId: number | null;
  token: string | null;
  profileNickname: string | null;
  profileUsername: string | null;
  isAdmin: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (nickname: string, username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);
const PROFILE_CACHE_KEY = 'msghub-profile-v1';

/**
 * Парсит userId из JWT токена.
 * Возвращает null если токен невалидный.
 */
function parseUserId(token: string | null): number | null {
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

/** user_id из тела ответа или из JWT (если бэкенд не отдал поле). */
function userIdFromAuthPayload(data: { access_token: string; user_id?: number }): number | null {
  const raw = data.user_id;
  if (raw != null) {
    const n = Number(raw);
    if (Number.isFinite(n)) return n;
  }
  return parseUserId(data.access_token);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [userId, setUserId] = useState<number | null>(null);
  const [profileNickname, setProfileNickname] = useState<string | null>(null);
  const [profileUsername, setProfileUsername] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);

  const saveProfile = useCallback((nickname: string | null, username: string | null) => {
    setProfileNickname(nickname);
    setProfileUsername(username);
    try {
      if (!nickname && !username) {
        localStorage.removeItem(PROFILE_CACHE_KEY);
      } else {
        localStorage.setItem(PROFILE_CACHE_KEY, JSON.stringify({ nickname, username }));
      }
    } catch {
      // ignore storage errors
    }
  }, []);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(PROFILE_CACHE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as { nickname?: string; username?: string };
      if (parsed.nickname) setProfileNickname(parsed.nickname);
      if (parsed.username) setProfileUsername(parsed.username);
    } catch {
      // ignore parse errors
    }
  }, []);

  const logout = useCallback(() => {
    auth.logout().catch(() => {
      // Даже если сервер недоступен, локально выходим.
    });
    setAccessToken(null);
    setToken(null);
    setUserId(null);
    setIsAdmin(false);
    saveProfile(null, null);
  }, [saveProfile]);

  // Синхронизация после авто-refresh в axios (api.ts)
  useEffect(() => {
    const onTokensRefreshed = (e: Event) => {
      const ce = e as CustomEvent<{ access_token: string; user_id?: number }>;
      const d = ce.detail;
      if (!d?.access_token) return;
      setAccessToken(d.access_token);
      setToken(d.access_token);
      setUserId(userIdFromAuthPayload(d));
    };
    const onAuthFailed = () => logout();
    window.addEventListener('msghub:tokens-refreshed', onTokensRefreshed);
    window.addEventListener('msghub:auth-failed', onAuthFailed);
    return () => {
      window.removeEventListener('msghub:tokens-refreshed', onTokensRefreshed);
      window.removeEventListener('msghub:auth-failed', onAuthFailed);
    };
  }, [logout]);

  // Восстанавливаем сессию на старте через refresh-cookie.
  useEffect(() => {
    auth.refresh().catch(() => {
      setAccessToken(null);
      setToken(null);
      setUserId(null);
    });
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const { data } = await auth.login(username, password);
    setAccessToken(data.access_token);
    setToken(data.access_token);
    setUserId(userIdFromAuthPayload(data));
    const me = await auth.getMe();
    saveProfile(me.data.nickname, me.data.username);
    setIsAdmin(Boolean(me.data.is_admin));
  }, [saveProfile]);

  const register = useCallback(async (nickname: string, username: string, password: string) => {
    const { data } = await auth.register(nickname, username, password);
    setAccessToken(data.access_token);
    setToken(data.access_token);
    setUserId(userIdFromAuthPayload(data));
    const me = await auth.getMe();
    saveProfile(me.data.nickname, me.data.username);
    setIsAdmin(Boolean(me.data.is_admin));
  }, [saveProfile]);

  return (
    <AuthContext.Provider value={{ userId, token, profileNickname, profileUsername, isAdmin, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be inside AuthProvider');
  return ctx;
}
