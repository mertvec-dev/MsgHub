/** Русские подписи для ключей прав из backend (rbac.Permission). */
export const PERMISSION_LABEL_RU: Record<string, string> = {
  manage_users: 'Управление пользователями',
  manage_roles: 'Управление ролями',
  ban_users: 'Бан пользователей',
  view_audit_logs: 'Просмотр журнала аудита',
  manage_rooms: 'Управление комнатами',
  mute_members: 'Заглушение участников',
};

export function formatPermissionsRu(keys: string[]): string {
  if (!keys.length) return '—';
  const sorted = [...keys].sort((a, b) =>
    (PERMISSION_LABEL_RU[a] ?? a).localeCompare(PERMISSION_LABEL_RU[b] ?? b, 'ru'),
  );
  return sorted.map((k) => PERMISSION_LABEL_RU[k] ?? k).join(', ');
}

/** Ключи прав в порядке русских подписей (для чипов в UI). */
export function sortedPermissionKeysRu(keys: string[]): string[] {
  return [...keys].sort((a, b) =>
    (PERMISSION_LABEL_RU[a] ?? a).localeCompare(PERMISSION_LABEL_RU[b] ?? b, 'ru'),
  );
}

export const ROLE_LABEL_RU: Record<string, string> = {
  user: 'Пользователь',
  moderator: 'Модератор',
  super_admin: 'Супер-админ',
};

export function roleLabelRu(role: string): string {
  return ROLE_LABEL_RU[role] ?? role;
}
