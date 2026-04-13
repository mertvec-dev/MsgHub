import { useEffect, useRef, useState } from 'react';

import {
  loadPendingOutbox,
  savePendingOutbox,
  type PendingOutboxItem,
} from '../storage/pendingOutboxStorage';
import { pendingOutboxStorageKey } from '../utils/common';

export function usePendingOutbox(userId: number | null | undefined) {
  const [pendingOutbox, setPendingOutbox] = useState<PendingOutboxItem[]>([]);
  const pendingOutboxRef = useRef<PendingOutboxItem[]>([]);

  useEffect(() => {
    const storageKey = pendingOutboxStorageKey(userId);
    setPendingOutbox(loadPendingOutbox(storageKey));
  }, [userId]);

  useEffect(() => {
    pendingOutboxRef.current = pendingOutbox;
  }, [pendingOutbox]);

  useEffect(() => {
    const storageKey = pendingOutboxStorageKey(userId);
    savePendingOutbox(storageKey, pendingOutbox);
  }, [pendingOutbox, userId]);

  return { pendingOutbox, setPendingOutbox, pendingOutboxRef };
}

