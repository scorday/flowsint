/** Property links only navigate to HTTP(S), without embedded credentials. */
export function propertyUrl(value: unknown): URL | null {
  if (typeof value !== 'string' || !/^https?:\/\//i.test(value)) return null
  try {
    const url = new URL(value)
    if (!url.hostname || url.username || url.password) return null
    return url
  } catch {
    return null
  }
}
