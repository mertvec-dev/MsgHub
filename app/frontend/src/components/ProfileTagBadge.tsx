/** Глобальный тег профиля (назначается администратором), показывается рядом с ником. */
export function ProfileTagBadge({ tag }: { tag?: string | null }) {
  const t = tag?.trim();
  if (!t) return null;
  return <span className="profile-tag-badge">{t}</span>;
}
