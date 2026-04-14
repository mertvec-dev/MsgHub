import { useState, useEffect, useCallback } from 'react';
import type { ReactNode } from 'react';
import { auth, setAccessToken, getAccessToken, type User } from '../services/api';
import { userIdFromAuthPayload } from './authHelpers';
import { AuthContext } from './authContextObject';
const PROFILE_CACHE_KEY = 'msghub-profile-v1';

/** Доступ к админ-разделу: флаг или роль staff (на случай рассинхрона is_admin). */
function userHasStaffAccess(me: User): boolean {
  if (me.is_admin) return true;
  const r = me.role;
  return r === 'moderator' || r === 'super_admin';
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [userId, setUserId] = useState<number | null>(null);
  const [profileNickname, setProfileNickname] = useState<string | null>(null);
  const [profileUsername, setProfileUsername] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [isStaff, setIsStaff] = useState(false);
  const [userRole, setUserRole] = useState<'user' | 'moderator' | 'super_admin' | null>(null);

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
    setIsStaff(false);
    setUserRole(null);
    saveProfile(null, null);
  }, [saveProfile]);

  useEffect(() => {
    const onTokensRefreshed = (e: Event) => {
      const ce = e as CustomEvent<{ access_token: string; user_id?: number }>;
      const d = ce.detail;
      if (!d?.access_token) return;
      setAccessToken(d.access_token);
      setToken(d.access_token);
      setUserId(userIdFromAuthPayload(d));
      void auth.getMe().then((res) => {
        const staff = userHasStaffAccess(res.data);
        setIsAdmin(staff);
        setIsStaff(staff);
        setUserRole(res.data.role ?? null);
      }).catch(() => {});
    };
    const onAuthFailed = () => logout();
    window.addEventListener('msghub:tokens-refreshed', onTokensRefreshed);
    window.addEventListener('msghub:auth-failed', onAuthFailed);
    return () => {
      window.removeEventListener('msghub:tokens-refreshed', onTokensRefreshed);
      window.removeEventListener('msghub:auth-failed', onAuthFailed);
    };
  }, [logout]);

  useEffect(() => {
    void (async () => {
      try {
        await auth.refresh();
        const me = await auth.getMe();
        saveProfile(me.data.nickname, me.data.username);
        setUserId(me.data.id);
        const staff = userHasStaffAccess(me.data);
        setIsAdmin(staff);
        setIsStaff(staff);
        setUserRole(me.data.role ?? null);
        setToken(getAccessToken());
      } catch {
        setAccessToken(null);
        setToken(null);
        setUserId(null);
        setIsAdmin(false);
        setIsStaff(false);
        setUserRole(null);
      }
    })();
  }, [saveProfile]);

  const login = useCallback(
    async (username: string, password: string) => {
      const { data } = await auth.login(username, password);
      setAccessToken(data.access_token);
      setToken(data.access_token);
      setUserId(userIdFromAuthPayload(data));
      const me = await auth.getMe();
      saveProfile(me.data.nickname, me.data.username);
      const staff = userHasStaffAccess(me.data);
      setIsAdmin(staff);
      setIsStaff(staff);
      setUserRole(me.data.role ?? null);
    },
    [saveProfile]
  );

  const register = useCallback(
    async (nickname: string, username: string, password: string) => {
      const { data } = await auth.register(nickname, username, password);
      setAccessToken(data.access_token);
      setToken(data.access_token);
      setUserId(userIdFromAuthPayload(data));
      const me = await auth.getMe();
      saveProfile(me.data.nickname, me.data.username);
      const staff = userHasStaffAccess(me.data);
      setIsAdmin(staff);
      setIsStaff(staff);
      setUserRole(me.data.role ?? null);
    },
    [saveProfile]
  );

  return (
    <AuthContext.Provider
      value={{
        userId,
        token,
        profileNickname,
        profileUsername,
        isAdmin,
        isStaff,
        userRole,
        login,
        register,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

