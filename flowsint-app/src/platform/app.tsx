import { useTranslation } from '@/i18n'
import { LanguageSwitcher } from '@/components/language-switcher'
import type { ReactNode } from 'react'
import { createPlatformApp } from '@avl4/core-sdk-react/app'
import { queryClient } from './query-client'
import { runtimeConfig } from './runtime-config'
import { resetProjectState } from './reset-state'

function State({ children }: { children: ReactNode }) {
  const { t } = useTranslation()
  return (
    <main className="platform-state" role="status">
      <p>{typeof children === 'string' ? t(children) : children}</p>
      <LanguageSwitcher />
    </main>
  )
}

export const platformFallbacks = {
  loading: <State>Connecting to AVL4…</State>,
  missing: (
    <State>
      The AVL4 panel did not load. Refresh the page or open Flowsint from the main menu.
    </State>
  ),
  incompatible: (
    <State>The AVL4 panel version is incompatible with Flowsint. Refresh the page.</State>
  ),
  anonymous: <State>Sign in to AVL4 through the shared panel.</State>,
  reauthenticationRequired: (
    <State>Your session expired. Continue signing in through the AVL4 panel.</State>
  ),
  error: <State>Could not connect to AVL4. Check your connection and refresh the page.</State>,
  noAccess: <State>You do not have access to Flowsint. Contact your administrator.</State>,
  projectLoading: <State>Loading project…</State>,
  projectUnavailable: (
    <State>The project is unavailable. Select an available project in the AVL4 panel.</State>
  )
}

let app: ReturnType<typeof createPlatformApp> | undefined
export function getPlatformApp() {
  return (app ??= createPlatformApp({
    appId: 'flowsint',
    projectScoped: true,
    queryClient,
    axios: { baseURL: runtimeConfig.get().apiBaseUrl, withCredentials: true },
    resetUserState: resetProjectState,
    fallbacks: platformFallbacks
  }))
}

if (import.meta.hot) import.meta.hot.dispose(() => app?.dispose())
