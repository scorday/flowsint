import { createPlatformHost, installPlatformClient, type PlatformHost } from '@avl4/core-sdk'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { platformUser } from './fixtures.test-support'

let host: PlatformHost
let app: ReturnType<(typeof import('./app'))['getPlatformApp']>
let source: ReadableStreamDefaultController<Uint8Array>
let received!: Request
let cancel: ReturnType<typeof vi.fn>
const encode = (value: string) => new TextEncoder().encode(value)

beforeEach(async () => {
  vi.stubGlobal('window', { location: { origin: 'http://localhost' } })
  vi.resetModules()
  vi.stubEnv('VITE_AUTH_MODE', 'avl4')
  vi.stubEnv('VITE_RUNTIME_CONFIG', 'false')
  host = createPlatformHost()
  host.initializeAuthenticated(platformUser())
  host.selectProject('project-a')
  installPlatformClient(host.client)
  cancel = vi.fn()
  app = (await import('./app')).getPlatformApp()
  app.http.defaults.baseURL = 'http://localhost'
  received = undefined as never
  app.http.defaults.env = {
    ...app.http.defaults.env,
    fetch: vi.fn<typeof fetch>(async (input, init) => {
      received = new Request(input, init)
      return new Response(
        new ReadableStream<Uint8Array>({
          start(controller) {
            source = controller
          },
          cancel
        }),
        { headers: { 'content-type': 'text/event-stream' } }
      )
    })
  }
})
afterEach(() => {
  app.dispose()
  host.destroy()
  vi.unstubAllEnvs()
  Reflect.deleteProperty(window, '__AVL_PLATFORM__')
  vi.unstubAllGlobals()
})

describe('platform streams', () => {
  it('uses the SDK event stream and closes it when the project changes', async () => {
    const { connectSSE } = await import('@/api/sse')
    const onMessage = vi.fn()
    const dispose = connectSSE({ url: '/api/events/sketch/a/stream', onMessage })
    await vi.waitFor(() => expect(received).toBeTruthy())
    expect(received.headers.get('h-avl-project')).toBe('project-a')
    source.enqueue(encode('data: {"event":"log","data":"safe"}\n\n'))
    await vi.waitFor(() => expect(onMessage).toHaveBeenCalledWith({ event: 'log', data: 'safe' }))
    host.selectProject('project-b')
    await vi.waitFor(() => expect(received.signal.aborted).toBe(true))
    expect(onMessage).toHaveBeenCalledTimes(1)
    dispose()
  })

  it.each(['project', 'logout', 'session'])(
    'cancels AI POST streaming on %s change',
    async (change) => {
      const { platformChatFetch } = await import('./chat-fetch')
      const response = await platformChatFetch('http://localhost/api/chats/stream/chat-a', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: '{"prompt":"hello"}'
      })
      expect(received.method).toBe('POST')
      expect(received.headers.get('h-avl-project')).toBe('project-a')
      const reader = response.body!.getReader()
      source.enqueue(encode('data: {"type":"start"}\n\n'))
      expect((await reader.read()).done).toBe(false)
      const next = reader.read()
      const rejected = expect(next).rejects.toBeTruthy()
      if (change === 'project') host.selectProject('project-b')
      if (change === 'logout') host.completeLogout()
      if (change === 'session') host.initializeAuthenticated(platformUser('new-user'))
      await rejected
      expect(cancel).toHaveBeenCalled()
    }
  )
})
