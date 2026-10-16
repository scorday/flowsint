import type { ReactNode } from 'react'
import { createPlatformApp } from '@avl4/core-sdk-react/app'
import { queryClient } from './query-client'
import { runtimeConfig } from './runtime-config'
import { resetProjectState } from './reset-state'

function State({ children }: { children: ReactNode }) {
  return (
    <main className="platform-state" role="status">
      <p>{children}</p>
    </main>
  )
}

export const platformFallbacks = {
  loading: <State>Подключение к AVL4…</State>,
  missing: (
    <State>
      Панель AVL4 не загрузилась. Обновите страницу или откройте Flowsint через главное меню.
    </State>
  ),
  incompatible: <State>Версия панели AVL4 несовместима с Flowsint. Обновите страницу.</State>,
  anonymous: <State>Войдите в AVL4 через общую панель.</State>,
  reauthenticationRequired: <State>Сессия истекла. Продолжите вход через панель AVL4.</State>,
  error: <State>Не удалось подключиться к AVL4. Проверьте соединение и обновите страницу.</State>,
  noAccess: <State>Нет доступа к Flowsint. Обратитесь к администратору.</State>,
  projectLoading: <State>Загрузка проекта…</State>,
  projectUnavailable: <State>Проект недоступен. Выберите доступный проект в панели AVL4.</State>
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
