import { useEffect, useState } from 'react';
import '../styles/ServiceModal.css';

export function PromptDialog({
  open,
  title,
  label,
  defaultValue = '',
  placeholder,
  submitLabel = 'Сохранить',
  cancelLabel = 'Отмена',
  onSubmit,
  onCancel,
}: {
  open: boolean;
  title: string;
  label: string;
  defaultValue?: string;
  placeholder?: string;
  submitLabel?: string;
  cancelLabel?: string;
  onSubmit: (value: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(defaultValue);

  useEffect(() => {
    if (open) setValue(defaultValue);
  }, [open, defaultValue]);

  if (!open) return null;

  const submit = () => {
    onSubmit(value);
  };

  return (
    <div className="srv-modal-overlay" role="presentation" onClick={onCancel}>
      <div
        className="srv-modal srv-modal-sm"
        role="dialog"
        aria-modal="true"
        aria-labelledby="srv-prompt-title"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            submit();
          }
        }}
      >
        <div className="srv-modal-header">
          <h2 id="srv-prompt-title">{title}</h2>
          <button type="button" className="srv-modal-close" onClick={onCancel} aria-label="Закрыть">
            ✕
          </button>
        </div>
        <div className="srv-modal-body">
          <div className="srv-form-group">
            <label htmlFor="srv-prompt-input">{label}</label>
            <input
              id="srv-prompt-input"
              autoFocus
              value={value}
              placeholder={placeholder}
              onChange={(e) => setValue(e.target.value)}
            />
          </div>
        </div>
        <div className="srv-modal-footer">
          <button type="button" className="srv-btn srv-btn-secondary" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button type="button" className="srv-btn srv-btn-primary" onClick={submit}>
            {submitLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
