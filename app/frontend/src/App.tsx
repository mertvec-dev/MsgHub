import { AuthProvider } from './context/AuthContext';
import { ToastProvider } from './context/ToastContext';
import { useAuth } from './context/useAuth';
import ToastContainer from './components/ToastContainer';
import LoginPage from './pages/LoginPage';
import ChatPage from './pages/ChatPage';

function AppContent() {
  const { token } = useAuth();
  return token ? <ChatPage /> : <LoginPage />;
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
