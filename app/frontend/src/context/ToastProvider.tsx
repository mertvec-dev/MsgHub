import { useState } from 'react';
import type { ReactNode } from 'react';
import { createToastId } from './toastHelpers';
import { ToastContext, type Toast, type ToastType } from './toastContextObject';

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const showToast = (message: string, type: ToastType = 'info', duration = 4000) => {
    const id = createToastId();
    const newToast: Toast = { id, message, type, duration };

    setToasts((prev) => [...prev, newToast]);

    if (duration > 0) {
      setTimeout(() => removeToast(id), duration);
    }
  };

  const removeToast = (id: string) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  };

  return <ToastContext.Provider value={{ toasts, showToast, removeToast }}>{children}</ToastContext.Provider>;
}

