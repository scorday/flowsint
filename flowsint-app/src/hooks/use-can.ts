import { isAvl4 } from '@/platform/runtime-config'
import { useMemo } from 'react'
import { useRouterState } from '@tanstack/react-router'
import type { InvestigationRole } from '@/types'

type Action = 'read' | 'create' | 'update' | 'delete' | 'manage'

export type Permissions = {
  can: (action: Action) => boolean
  canEdit: boolean
  canCreate: boolean
  canDelete: boolean
  canManage: boolean
  isViewer: boolean
  isOwner: boolean
  role: InvestigationRole | null
}

const ROLE_LEVEL: Record<InvestigationRole, number> = {
  owner: 4,
  admin: 3,
  editor: 2,
  viewer: 1
}

function canRolePerform(role: InvestigationRole | null, action: Action): boolean {
  if (!role) return false
  const level = ROLE_LEVEL[role]
  switch (action) {
    case 'read':
      return level >= 1
    case 'create':
    case 'update':
      return level >= 2
    case 'manage':
      return level >= 3
    case 'delete':
      return level >= 4
    default:
      return false
  }
}

export function useCan(role: InvestigationRole | null | undefined): Permissions {
  return useMemo(() => {
    const r = role ?? null
    const can = (action: Action) => isAvl4 || canRolePerform(r, action)
    return {
      can,
      canEdit: can('update'),
      canCreate: can('create'),
      canDelete: can('delete'),
      canManage: can('manage'),
      isViewer: !isAvl4 && r === 'viewer',
      isOwner: !isAvl4 && r === 'owner',
      role: isAvl4 ? null : r
    }
  }, [role])
}

/**
 * Read permissions from the $investigationId layout route loader data.
 * Works anywhere rendered under that route — including components in
 * RootLayout like DetailsPanel, since the route is active when they render.
 */
export function usePermissions(): Permissions {
  const role = useRouterState({
    select: (state) => {
      const data = state.matches.find(
        (match) => match.routeId === '/_auth/dashboard/investigations/$investigationId'
      )?.loaderData
      return data && 'investigation' in data ? data.investigation.current_user_role : null
    }
  })
  return useCan(role)
}
