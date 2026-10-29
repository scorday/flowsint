// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { enricherAdministrationService } from '@/api/enricher-administration-service'
import { Sidebar } from './sidebar'

vi.mock('@/api/enricher-administration-service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/enricher-administration-service')>()),
  enricherAdministrationService: { access: vi.fn() }
}))
vi.mock('@/platform/runtime-config', () => ({ isAvl4: true }))
vi.mock('@/components/nav-user', () => ({ NavUser: () => null }))
vi.mock('@/config', () => ({ CONFIG: { ENRICHER_TEMPLATES_FEATURE_FLAG: false } }))
vi.mock('@tanstack/react-router', () => ({
  Link: ({
    to,
    children,
    className,
    ...props
  }: {
    to: string
    children: ReactNode
    className: string
    'aria-label': string
  }) => (
    <a href={to} className={className} aria-label={props['aria-label']}>
      {children}
    </a>
  )
}))

let client: QueryClient
afterEach(() => {
  cleanup()
  client.clear()
  vi.clearAllMocks()
})
function mount() {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <Sidebar />
    </QueryClientProvider>
  )
}

describe('Enricher administration navigation', () => {
  it('shows the server-authorized administration link even when template editing is disabled', async () => {
    vi.mocked(enricherAdministrationService.access).mockResolvedValue({ can_manage: true })
    mount()
    const link = await screen.findByRole('link', { name: 'Enricher administration' })
    expect(link.getAttribute('href')).toBe('/dashboard/admin/enrichers')
    expect(screen.queryByRole('link', { name: 'Enrichers' })).toBeNull()
  })

  it('hides administration navigation when the server denies capability', async () => {
    vi.mocked(enricherAdministrationService.access).mockResolvedValue({ can_manage: false })
    mount()
    await screen.findByRole('link', { name: 'Dashboard' })
    expect(screen.queryByRole('link', { name: 'Enricher administration' })).toBeNull()
  })
})
