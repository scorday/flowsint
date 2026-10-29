// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { createPlatformHost, installPlatformClient, type PlatformHost } from '@avl4/core-sdk'
import { AxiosError, AxiosHeaders } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { platformUser } from './fixtures.test-support'

const challenge = vi.fn()
let host: PlatformHost
let app: ReturnType<(typeof import('./app'))['getPlatformApp']>
let queries: (typeof import('./query-client'))['queryClient']

beforeEach(async () => {
  vi.resetModules()
  vi.stubEnv('VITE_AUTH_MODE', 'avl4')
  vi.stubEnv('VITE_RUNTIME_CONFIG', 'false')
  challenge.mockClear()
  const values = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key)
  })
  localStorage.setItem('flowsint-language', 'ru')
  host = createPlatformHost({ onUnauthorized: challenge })
  host.initializeAuthenticated(platformUser())
  host.selectProject('project-a')
  installPlatformClient(host.client)
  app = (await import('./app')).getPlatformApp()
  queries = (await import('./query-client')).queryClient
})
afterEach(() => {
  cleanup()
  app.dispose()
  host.destroy()
  queries.clear()
  vi.unstubAllEnvs()
  Reflect.deleteProperty(window, '__AVL_PLATFORM__')
  vi.unstubAllGlobals()
})

describe('Flowsint platform integration', () => {
  it('shows an incompatible panel state without mounting protected routes', async () => {
    Object.defineProperty(window, '__AVL_PLATFORM__', {
      value: { apiVersion: '1.0' },
      configurable: true
    })
    render(
      <app.Provider>
        <span>protected investigation</span>
      </app.Provider>
    )
    await screen.findByText('Версия панели AVL4 несовместима с Flowsint. Обновите страницу.')
    expect(screen.queryByText('protected investigation')).toBeNull()
  })

  it('shows a missing panel state after the SDK connection timeout', async () => {
    vi.useFakeTimers()
    try {
      Reflect.deleteProperty(window, '__AVL_PLATFORM__')
      render(
        <app.Provider>
          <span>protected investigation</span>
        </app.Provider>
      )
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_050)
      })
      expect(
        screen.getByText(
          'Панель AVL4 не загрузилась. Обновите страницу или откройте Flowsint через главное меню.'
        )
      ).toBeTruthy()
      expect(screen.queryByText('protected investigation')).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })

  it('sends cookie credentials and the current project without a legacy Bearer token', async () => {
    const { fetchWithAuth } = await import('@/api/api')
    app.http.defaults.adapter = async (config) => {
      expect(config.withCredentials).toBe(true)
      expect(config.headers.get('h-avl-project')).toBe('project-a')
      expect(config.headers.get('Authorization')).toBeUndefined()
      return { status: 200, statusText: 'OK', data: { id: 'inv' }, headers: {}, config }
    }
    expect(await fetchWithAuth('/api/investigations')).toEqual({ id: 'inv' })
  })

  it('rejects a response completed after the panel changes project', async () => {
    let complete!: () => void
    let started!: () => void
    const admitted = new Promise<void>((resolve) => {
      started = resolve
    })
    app.http.defaults.adapter = (config) =>
      new Promise((resolve) => {
        complete = () =>
          resolve({ status: 200, statusText: 'OK', data: 'old secret', headers: {}, config })
        started()
      })
    const request = app.http.get('/api/investigations')
    const rejected = expect(request).rejects.toBeTruthy()
    await admitted
    host.selectProject('project-b')
    complete()
    await rejected
  })

  it.each([401, 403, 503])(
    'does not replay HTTP %s; only 401 challenges the panel',
    async (status) => {
      const adapter = vi.fn(async (config) => {
        throw new AxiosError('denied', 'ERR_BAD_RESPONSE', config, undefined, {
          status,
          statusText: 'Denied',
          data: {},
          headers: new AxiosHeaders({ 'X-AVL-Auth-Guard': 'session-rejected' }),
          config
        })
      })
      app.http.defaults.adapter = adapter
      await expect(app.http.post('/api/investigations/create', {})).rejects.toBeTruthy()
      expect(adapter).toHaveBeenCalledTimes(1)
      expect(challenge).toHaveBeenCalledTimes(status === 401 ? 1 : 0)
    }
  )

  it('clears Query, graph, chat and editor state on project change and hides data on logout', async () => {
    const { useGraphStore } = await import('@/stores/graph-store')
    const { useChatState } = await import('@/stores/use-chat-store')
    const { useFlowStore } = await import('@/stores/flow-store')
    const { useGraphSettingsStore } = await import('@/stores/graph-settings-store')
    render(
      <app.Provider>
        <span>protected investigation</span>
      </app.Provider>
    )
    await screen.findByText('protected investigation')
    queries.setQueryData(['secret'], 'project-a')
    useChatState.getState().setCurrentChatId('chat-a')
    useGraphSettingsStore.getState().setImportModalOpen(true)
    useFlowStore.setState({ selectedNode: { id: 'flow-secret' } as never })
    useGraphStore.setState({ currentNodeId: 'node-a', nodes: [{ id: 'node-a' } as never] })
    act(() => host.selectProject('project-b'))
    await waitFor(() => expect(useGraphStore.getState().nodes).toEqual([]))
    expect(queries.getQueryData(['secret'])).toBeUndefined()
    expect(useChatState.getState().currentChatId).toBeNull()
    expect(useFlowStore.getState().selectedNode).toBeNull()
    expect(useGraphSettingsStore.getState().importModalOpen).toBe(false)
    act(() => host.completeLogout())
    expect(screen.queryByText('protected investigation')).toBeNull()
    expect(screen.getByText('Войдите в AVL4 через общую панель.')).toBeTruthy()
  })

  it('holds the application while the project is unavailable and rejects app access loss', async () => {
    host.clearProject()
    render(
      <app.Provider>
        <span>protected investigation</span>
      </app.Provider>
    )
    await screen.findByText('Проект недоступен. Выберите доступный проект в панели AVL4.')
    act(() => host.selectProject('project-a'))
    expect(screen.getByText('protected investigation')).toBeTruthy()
    act(() => host.updateUser({ ...platformUser(), roles: [], keycloakGroups: [] }))
    expect(screen.queryByText('protected investigation')).toBeNull()
    expect(screen.getByText('Нет доступа к Flowsint. Обратитесь к администратору.')).toBeTruthy()
  })
})
