import { describe, expect, it } from 'vitest'
import { propertyUrl } from './property-url'

describe('property links', () => {
  it('preserves the Monitoring card and project context on local HTTP', () => {
    const source = 'http://feed.avl4.localhost/feed?cardId=card-a#pid=project-a'
    expect(propertyUrl(source)?.href).toBe(source)
  })

  it('supports external HTTPS sources', () => {
    expect(propertyUrl('https://example.org/article')?.hostname).toBe('example.org')
  })

  it.each([
    'javascript:alert(1)',
    'data:text/html,test',
    '//example.org',
    'https://',
    'https://user:secret@example.org',
    'ordinary text',
    null
  ])('does not render unsafe or invalid values as links: %s', (value) => {
    expect(propertyUrl(value)).toBeNull()
  })
})
