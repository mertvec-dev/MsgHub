import { useToast, type ToastType } from '../context/ToastContext';
import '../styles/Toast.css';

function getIcon(type: ToastType) {
  switch (type) {
    case 'success':
      return '✓';
    case 'error':
      return '✕';
    case 'warning':
      return '⚠';
    case 'info':
    default:
      return 'ℹ';
  }
}

function ToastItem({ id, message, type }: any) {
  const { removeToast } = useToast();

  return (
    <div className={`toast toast-${type}`}>
      <span className="toast-icon">{getIcon(type)}</span>
      <span className="toast-message">{message}</span>
      <button
        className="toast-close"
        onClick={() => removeToast(id)}
        aria-label="Close"
      >
        ✕
      </button>
    </div>
  );
}

export default function ToastContainer() {
  const { toasts } = useToast();

  return (
    <div className="toast-container">
      {toasts.map((toast) => (
        <ToastItem key={toast.id} {...toast} />
      ))}
    </div>
  );
}
