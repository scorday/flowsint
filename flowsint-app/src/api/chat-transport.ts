import { isAvl4, getApiBaseUrl } from '@/platform/runtime-config'
import { platformChatFetch } from '@/platform/chat-fetch'
import { DefaultChatTransport } from 'ai'
import { useAuthStore } from '@/stores/auth-store'

export function createChatTransport(chatId: string) {
  return new DefaultChatTransport({
    api: new URL(
      `api/chats/stream/${chatId}`,
      new URL(getApiBaseUrl().replace(/\/?$/, '/'), window.location.origin)
    ).href,
    ...(isAvl4 ? { fetch: platformChatFetch, credentials: 'include' as const } : {}),
    headers: (): Record<string, string> => {
      if (isAvl4) return {}
      const token = useAuthStore.getState().token
      if (token) return { Authorization: `Bearer ${token}` }
      return {}
    },
    prepareSendMessagesRequest: ({ messages, body }) => {
      const lastUserMessage = [...messages].reverse().find((m) => m.role === 'user')
      const prompt =
        lastUserMessage?.parts
          ?.filter((p): p is { type: 'text'; text: string } => p.type === 'text')
          .map((p) => p.text)
          .join('') ?? ''

      const context = (body as Record<string, unknown> | undefined)?.context
      return {
        body: { prompt, ...(context ? { context } : {}) }
      }
    }
  })
}
