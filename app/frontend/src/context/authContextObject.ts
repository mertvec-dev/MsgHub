import { createContext } from 'react';

export interface AuthContextType {
  userId: number | null;
  token: string | null;
  profileNickname: string | null;
  profileUsername: string | null;
  isAdmin: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (nickname: string, username: string, password: string) => Promise<void>;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextType | null>(null);

