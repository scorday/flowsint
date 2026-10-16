import { getPlatformClient } from '@avl4/core-sdk'
import { getPlatformApp } from './app'

/** AI SDK fetch contract, transported through the platform request gate. */
export const platformChatFetch: typeof fetch = async (input, init) => {
  const request = new Request(input, init)
  const client = getPlatformClient()
  if (!client) throw new Error('AVL4 platform is unavailable')
  const auth = client.auth.getSnapshot()
  const project = client.project.getSnapshot()
  const controller = new AbortController()
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined
  const close = () => {
    controller.abort()
    void reader?.cancel().catch(() => undefined)
  }
  const unsubscribe = client.events.subscribe((event) => {
    const currentProject = client.project.getSnapshot()
    if (
      event.snapshot.user?.id !== auth.user?.id ||
      event.snapshot.sessionEpoch !== auth.sessionEpoch ||
      ['auth.logout', 'auth.reauthentication-required', 'platform.error'].includes(event.type) ||
      !client.permissions.canAccessApp('flowsint') ||
      currentProject.revision !== project.revision
    )
      close()
  })
  request.signal.addEventListener('abort', close, { once: true })
  const cleanup = () => {
    unsubscribe()
    request.signal.removeEventListener('abort', close)
  }
  if (request.signal.aborted) close()
  try {
    const response = await getPlatformApp().http.request<ReadableStream<Uint8Array>>({
      url: request.url,
      method: request.method,
      data: await request.text(),
      headers: Object.fromEntries(request.headers.entries()),
      adapter: 'fetch',
      responseType: 'stream',
      signal: controller.signal
    })
    reader = response.data.getReader()
    const stream = new ReadableStream<Uint8Array>({
      async pull(output) {
        try {
          const chunk = await reader!.read()
          if (controller.signal.aborted) throw new DOMException('Context changed', 'AbortError')
          if (chunk.done) {
            cleanup()
            output.close()
          } else output.enqueue(chunk.value)
        } catch (error) {
          cleanup()
          close()
          output.error(error)
        }
      },
      cancel() {
        cleanup()
        close()
      }
    })
    return new Response(stream, {
      status: response.status,
      headers: { 'content-type': 'text/event-stream' }
    })
  } catch (error) {
    cleanup()
    close()
    throw error
  }
}
