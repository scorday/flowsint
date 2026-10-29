import type { User } from '@avl4/core-sdk'

export function platformUser(id = 'opaque-user'): User {
  return {
    id,
    username: 'investigator',
    firstName: null,
    lastName: null,
    avatarFileId: null,
    email: null,
    phone: null,
    company: null,
    theme: null,
    lang: null,
    timezone: null,
    createdAt: null,
    updatedAt: null,
    lastLoginAt: null,
    enabledAt: null,
    deletedAt: null,
    isEnabled: true,
    isDeleted: false,
    isAccessEnded: false,
    notifyByEmail: false,
    notifyByTelegram: false,
    roles: ['global_access_admin'],
    keycloakRoles: [],
    keycloakGroups: ['/Administrator'],
    hasPrivateProjectRole: false,
    access: { isEnabled: true, projects: [], apps: [] }
  }
}
