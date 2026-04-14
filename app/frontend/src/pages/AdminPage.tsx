import { useState, useEffect } from 'react';
import {
  auth,
  type User,
  type AdminOverview,
  type AdminAuditLogItem,
  type SecurityEventItem,
} from '../services/api';
import { useAuth } from '../context/useAuth';
import { useToast } from '../context/useToast';
import { apiErrorDetail } from '../chat/utils/apiError';
import { PERMISSION_LABEL_RU, roleLabelRu, sortedPermissionKeysRu } from '../admin/adminLabels';
import { ConfirmDialog } from '../components/ConfirmDialog';
import '../styles/AdminPage.css';

function adminBadgeEl(u: User) {
  if (u.role === 'super_admin') return <span className="admin-badge super">Супер-админ</span>;
  if (u.is_admin) return <span className="admin-badge">Админ</span>;
  return null;
}

export default function AdminPage() {
  const { userRole, logout } = useAuth();
  const { showToast } = useToast();
  const [myRole, setMyRole] = useState<'user' | 'moderator' | 'super_admin'>('user');
  const [myPermissions, setMyPermissions] = useState<string[]>([]);
  const [adminOverview, setAdminOverview] = useState<AdminOverview | null>(null);
  const [adminLogs, setAdminLogs] = useState<AdminAuditLogItem[]>([]);
  const [securityEvents, setSecurityEvents] = useState<SecurityEventItem[]>([]);
  const [searchQ, setSearchQ] = useState('');
  const [searchResults, setSearchResults] = useState<User[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);
  const [tagDraft, setTagDraft] = useState('');
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);

  const effectiveRole = (userRole ?? myRole) as 'user' | 'moderator' | 'super_admin';
  const canManageRoles = effectiveRole === 'super_admin';
  const canManageUsers = canManageRoles || myPermissions.includes('manage_users');
  const canBanUsers = canManageRoles || myPermissions.includes('ban_users');

  useEffect(() => {
    void auth.getMe().then((r) => setMyRole((r.data.role as typeof myRole) || 'user')).catch(() => {});
    void auth.adminOverview().then((r) => setAdminOverview(r.data)).catch(() => {});
    void auth.adminAuditLogs(30).then((r) => setAdminLogs(r.data || [])).catch(() => {});
    void auth.adminSecurityEvents(30).then((r) => setSecurityEvents(r.data || [])).catch(() => {});
    void auth.adminMyPermissions().then((r) => setMyPermissions(r.data.permissions || [])).catch(() => {});
  }, []);

  useEffect(() => {
    const t = window.setTimeout(() => {
      const q = searchQ.trim();
      if (!q) {
        setSearchResults([]);
        setSearchLoading(false);
        return;
      }
      setSearchLoading(true);
      void auth
        .adminSearchUsers(q, 40)
        .then((r) => setSearchResults(r.data || []))
        .catch((e) => {
          setSearchResults([]);
          showToast(apiErrorDetail(e, 'Ошибка поиска пользователей'), 'error');
        })
        .finally(() => setSearchLoading(false));
    }, 320);
    return () => window.clearTimeout(t);
  }, [searchQ]);

  useEffect(() => {
    if (selectedUser) setTagDraft(selectedUser.profile_tag ?? '');
  }, [selectedUser]);

  const reloadSelected = async (id: number) => {
    const r = await auth.adminSearchUsers(String(id), 5);
    const u = (r.data || []).find((x) => x.id === id);
    if (u) setSelectedUser(u);
  };

  return (
    <div className="admin-page">
      <header className="admin-page-header">
        <button type="button" className="admin-back" onClick={() => { window.location.hash = ''; }}>
          ← Чаты
        </button>
        <h1>Админ-панель</h1>
        <button type="button" className="admin-logout" onClick={() => logout()}>
          Выйти
        </button>
      </header>

      <div className="admin-page-body">
        <div className="admin-panel-col">
          <div className="admin-settings-section">
            <h4>Сводка</h4>
            <div className="admin-stat-row">
              <span>Моя роль</span>
              <span>{roleLabelRu(myRole)}</span>
            </div>
            <div className="admin-stat-row admin-stat-row--stack">
              <span className="admin-stat-label">Разрешения</span>
              {myPermissions.length === 0 ? (
                <span className="admin-perms-empty">—</span>
              ) : (
                <div className="admin-perms-tags">
                  {sortedPermissionKeysRu(myPermissions).map((k) => (
                    <span key={k} className="admin-perm-chip">
                      {PERMISSION_LABEL_RU[k] ?? k}
                    </span>
                  ))}
                </div>
              )}
            </div>
            {adminOverview && (
              <>
                <div className="admin-stat-row">
                  <span>Пользователей</span>
                  <span>{adminOverview.users_total}</span>
                </div>
                <div className="admin-stat-row">
                  <span>Забанено</span>
                  <span>{adminOverview.banned_total}</span>
                </div>
                <div className="admin-stat-row">
                  <span>Сообщений</span>
                  <span>{adminOverview.messages_total}</span>
                </div>
              </>
            )}
          </div>

          <div className="admin-settings-section">
            <h4>Поиск пользователя</h4>
            <input
              className="admin-search-input"
              placeholder="ID, @username, ник или тег…"
              value={searchQ}
              onChange={(e) => setSearchQ(e.target.value)}
            />
            <p className="admin-muted">{searchLoading ? 'Поиск…' : 'Выберите пользователя из списка'}</p>
            <div className="admin-search-results">
              {searchResults.map((u) => (
                <button
                  key={u.id}
                  type="button"
                  className={`admin-user-row ${selectedUser?.id === u.id ? 'selected' : ''}`}
                  onClick={() => setSelectedUser(u)}
                >
                  #{u.id} {u.nickname} <span style={{ opacity: 0.75 }}>@{u.username}</span>{' '}
                  {u.profile_tag ? <span style={{ color: '#7acbff' }}>[{u.profile_tag}]</span> : null}{' '}
                  {adminBadgeEl(u)}
                </button>
              ))}
            </div>
          </div>

          <div className="admin-settings-section">
            <h4>Audit log</h4>
            {adminLogs.slice(0, 15).map((log) => (
              <div key={log.id} className="admin-log-line">
                {new Date(log.created_at).toLocaleString('ru-RU')} · {log.action}
              </div>
            ))}
            <h4 style={{ marginTop: 16 }}>Security</h4>
            {securityEvents.slice(0, 12).map((evt) => (
              <div key={evt.id} className="admin-log-line">
                {new Date(evt.created_at).toLocaleString('ru-RU')} · {evt.event_type} · {evt.severity}
              </div>
            ))}
          </div>
        </div>

        <div className="admin-panel-col">
          {selectedUser ? (
            <div className="admin-detail-card">
              <h2 className="admin-detail-title">
                {selectedUser.nickname} <span style={{ fontWeight: 400, opacity: 0.8 }}>@{selectedUser.username}</span>{' '}
                {adminBadgeEl(selectedUser)}
              </h2>
              <p className="admin-muted">id: {selectedUser.id} · бан: {selectedUser.is_banned ? 'да' : 'нет'}</p>

              <div className="admin-actions">
                {canManageRoles && (
                  <>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={async () => {
                        try {
                          await auth.adminSetRole(selectedUser.id, 'user');
                          await reloadSelected(selectedUser.id);
                          showToast('Роль: user', 'success');
                        } catch (e) {
                          showToast(apiErrorDetail(e, 'Ошибка'), 'error');
                        }
                      }}
                    >
                      role: user
                    </button>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={async () => {
                        try {
                          await auth.adminSetRole(selectedUser.id, 'moderator');
                          await reloadSelected(selectedUser.id);
                          showToast('Роль: moderator', 'success');
                        } catch (e) {
                          showToast(apiErrorDetail(e, 'Ошибка'), 'error');
                        }
                      }}
                    >
                      moderator
                    </button>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={async () => {
                        try {
                          await auth.adminSetRole(selectedUser.id, 'super_admin');
                          await reloadSelected(selectedUser.id);
                          showToast('Роль: super_admin', 'success');
                        } catch (e) {
                          showToast(apiErrorDetail(e, 'Ошибка'), 'error');
                        }
                      }}
                    >
                      super_admin
                    </button>
                  </>
                )}
                {canBanUsers && (
                  <>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={async () => {
                        try {
                          await auth.adminBan(selectedUser.id);
                          await reloadSelected(selectedUser.id);
                          showToast('Пользователь забанен', 'success');
                        } catch (e) {
                          showToast(apiErrorDetail(e, 'Ошибка'), 'error');
                        }
                      }}
                    >
                      Бан
                    </button>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={async () => {
                        try {
                          await auth.adminUnban(selectedUser.id);
                          await reloadSelected(selectedUser.id);
                          showToast('Разбан', 'success');
                        } catch (e) {
                          showToast(apiErrorDetail(e, 'Ошибка'), 'error');
                        }
                      }}
                    >
                      Разбан
                    </button>
                  </>
                )}
                {canManageUsers && (
                  <button
                    type="button"
                    className="btn-secondary danger"
                    onClick={() => setDeleteConfirmOpen(true)}
                  >
                    Удалить аккаунт
                  </button>
                )}
              </div>

              {canManageUsers && (
                <>
                  <input
                    className="profile-input"
                    placeholder="Глобальный тег профиля"
                    value={tagDraft}
                    onChange={(e) => setTagDraft(e.target.value)}
                  />
                  <div className="admin-actions">
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={async () => {
                        try {
                          await auth.adminSetUserTag(selectedUser.id, tagDraft.trim());
                          await reloadSelected(selectedUser.id);
                          showToast('Тег сохранён', 'success');
                        } catch (e) {
                          showToast(apiErrorDetail(e, 'Не удалось сохранить тег'), 'error');
                        }
                      }}
                    >
                      Сохранить тег
                    </button>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={async () => {
                        try {
                          await auth.adminClearUserTag(selectedUser.id);
                          setTagDraft('');
                          await reloadSelected(selectedUser.id);
                          showToast('Тег сброшен', 'success');
                        } catch (e) {
                          showToast(apiErrorDetail(e, 'Ошибка'), 'error');
                        }
                      }}
                    >
                      Сбросить тег
                    </button>
                  </div>
                </>
              )}

              {!canManageRoles && (
                <p className="admin-muted">Смена ролей — только у super_admin. Ban/тег — у модераторов с правами.</p>
              )}
            </div>
          ) : (
            <p className="admin-muted">Найдите пользователя слева и выберите строку, чтобы выполнить действия.</p>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={deleteConfirmOpen && selectedUser != null}
        title="Удалить аккаунт"
        message={
          selectedUser
            ? `Удалить аккаунт @${selectedUser.username}? Действие необратимо.`
            : ''
        }
        confirmLabel="Удалить"
        cancelLabel="Отмена"
        danger
        onCancel={() => setDeleteConfirmOpen(false)}
        onConfirm={async () => {
          if (!selectedUser) return;
          setDeleteConfirmOpen(false);
          try {
            await auth.adminDeleteUser(selectedUser.id);
            showToast('Аккаунт удалён', 'success');
            setSelectedUser(null);
            setSearchQ('');
          } catch (e) {
            showToast(apiErrorDetail(e, 'Не удалось удалить'), 'error');
          }
        }}
      />
    </div>
  );
}
