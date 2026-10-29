import { withProjectIdFragment } from '@avl4/core-sdk'

const key = 'flowsint.route-context.v1'
type Context = { userId: string; projectId: string }
type Storage = Pick<globalThis.Storage, 'getItem' | 'setItem'>

export function rememberProjectRoute(context: Context, pathname: string, storage: Storage) {
  try {
    storage.setItem(key, JSON.stringify({ ...context, pathname }))
  } catch {
    // Storage can be unavailable in a restricted browser; API isolation still applies.
  }
}

/** Main Panel changes pid and reloads; recognize the route left by the old scope. */
export function restoredProjectRoute(context: Context, url: URL, storage: Storage): string | null {
  try {
    const previous = JSON.parse(storage.getItem(key) ?? 'null')
    if (
      previous &&
      typeof previous.userId === 'string' &&
      typeof previous.projectId === 'string' &&
      previous.pathname === url.pathname &&
      (previous.userId !== context.userId || previous.projectId !== context.projectId)
    ) {
      return withProjectIdFragment('/dashboard', context.projectId)
    }
  } catch {
    // Invalid/disabled storage must not prevent startup.
  }
  return null
}
