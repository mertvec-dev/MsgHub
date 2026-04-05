import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import type { ReactNode } from 'react';
import { auth } from '../services/api';

interface AuthContextType {
  userId: number | null;
  token: string | null;
  login: (username: string, password: string) => Promise<void>;
  register: (nickname: string, username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

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
  // Инициализируем из localStorage — безопасно
  const storedToken = localStorage.getItem('access_token');
  const [token, setToken] = useState<string | null>(storedToken);
  const [userId, setUserId] = useState<number | null>(() => parseUserId(storedToken));

  // Если при загрузке токен оказался битым — чистим
  useEffect(() => {
    if (token && !userId) {
      console.warn('⚠️ Битый токен в localStorage — очищаю');
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      setToken(null);
    }
  }, []); // только при монтировании

  const logout = useCallback(() => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    setToken(null);
    setUserId(null);
  }, []);

  // Синхронизация после авто-refresh в axios (api.ts)
  useEffect(() => {
    const onTokensRefreshed = (e: Event) => {
      const ce = e as CustomEvent<{ access_token: string; refresh_token: string; user_id?: number }>;
      const d = ce.detail;
      if (!d?.access_token) return;
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

  const login = useCallback(async (username: string, password: string) => {
    const { data } = await auth.login(username, password);
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    setToken(data.access_token);
    setUserId(userIdFromAuthPayload(data));
  }, []);

  const register = useCallback(async (nickname: string, username: string, password: string) => {
    const { data } = await auth.register(nickname, username, password);
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    setToken(data.access_token);
    setUserId(userIdFromAuthPayload(data));
  }, []);

  return (
    <AuthContext.Provider value={{ userId, token, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be inside AuthProvider');
  return ctx;
}
