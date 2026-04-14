import '../styles/ServiceModal.css';

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'ОК',
  cancelLabel = 'Отмена',
  danger,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  onConfirm: () => void | Promise<void>;
  onCancel: () => void;
}) {
  if (!open) return null;
  return (
    <div className="srv-modal-overlay" role="presentation" onClick={onCancel}>
      <div
        className="srv-modal srv-modal-sm"
        role="dialog"
        aria-modal="true"
        aria-labelledby="srv-confirm-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="srv-modal-header">
          <h2 id="srv-confirm-title">{title}</h2>
          <button type="button" className="srv-modal-close" onClick={onCancel} aria-label="Закрыть">
            ✕
          </button>
        </div>
        <div className="srv-modal-body">
          <p className="srv-modal-text">{message}</p>
        </div>
        <div className="srv-modal-footer">
          <button type="button" className="srv-btn srv-btn-secondary" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button
            type="button"
            className={`srv-btn ${danger ? 'srv-btn-danger' : 'srv-btn-primary'}`}
            onClick={() => void Promise.resolve(onConfirm())}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
