import { useState } from 'react';
import { useAuth } from '../context/useAuth';
import { apiErrorDetail } from '../chat/utils/apiError';
import '../styles/Login.css';

export default function LoginPage() {
  const { login, register } = useAuth();
  const [isRegister, setIsRegister] = useState(false);
  const [nickname, setNickname] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      if (isRegister) {
        if (password.length < 8) throw new Error('Пароль минимум 8 символов');
        await register(nickname, username, password);
      } else {
        await login(username, password);
      }
    } catch (err: unknown) {
      setError(apiErrorDetail(err, 'Ошибка'));
    }
  };

  return (
    <div className="login-page">
      <div className="login-box">
        <h1>MsgHub</h1>
        <p className="subtitle">{isRegister ? 'Создать аккаунт' : 'С возвращением!'}</p>

        <form onSubmit={handleSubmit}>
          {isRegister && (
            <input
              type="text"
              placeholder="Никнейм"
              value={nickname}
              onChange={(e) => setNickname(e.target.value)}
              required
            />
          )}
          <input
            type="text"
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
          <input
            type="password"
            placeholder="Пароль"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          {error && <p className="error">{error}</p>}
          <button type="submit">{isRegister ? 'Зарегистрироваться' : 'Войти'}</button>
        </form>

        <button className="toggle-btn" onClick={() => setIsRegister(!isRegister)}>
          {isRegister ? 'Уже есть аккаунт? Войти' : 'Нет аккаунта? Регистрация'}
        </button>
      </div>
    </div>
  );
}
