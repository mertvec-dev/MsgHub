import { useState, useEffect } from 'react';
import { AuthProvider } from './context/AuthContext';
import { ToastProvider } from './context/ToastContext';
import { useAuth } from './context/useAuth';
import ToastContainer from './components/ToastContainer';
import LoginPage from './pages/LoginPage';
import ChatPage from './pages/ChatPage';
import AdminPage from './pages/AdminPage';

function AppContent() {
  const { token, isStaff } = useAuth();
  const [hash, setHash] = useState(() => (typeof window !== 'undefined' ? window.location.hash : ''));

  useEffect(() => {
    const onHash = () => setHash(window.location.hash);
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  useEffect(() => {
    if (token && hash === '#/admin' && !isStaff) {
      window.location.hash = '';
    }
  }, [token, hash, isStaff]);

  if (!token) return <LoginPage />;
  if (hash === '#/admin' && isStaff) return <AdminPage />;
  return <ChatPage />;
}

export default function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <AppContent />
        <ToastContainer />
      </AuthProvider>
    </ToastProvider>
  );
}
