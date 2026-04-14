import { createContext } from 'react';

export interface AuthContextType {
  userId: number | null;
  token: string | null;
  profileNickname: string | null;
  profileUsername: string | null;
  /** Совместимость: true если есть админ-флаг или роль staff */
  isAdmin: boolean;
  /** Доступ к админ-панели (moderator / super_admin / is_admin) */
  isStaff: boolean;
  userRole: 'user' | 'moderator' | 'super_admin' | null;
  login: (username: string, password: string) => Promise<void>;
  register: (nickname: string, username: string, password: string) => Promise<void>;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextType | null>(null);

