// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import NewSketch from './new-sketch'

const { create, navigate } = vi.hoisted(() => ({ create: vi.fn(), navigate: vi.fn() }))
vi.mock('@/api/sketch-service', () => ({ sketchService: { create } }))
vi.mock('@tanstack/react-router', () => ({
  useParams: () => ({ investigationId: 'case', id: 'friends' }),
  useRouter: () => ({ navigate })
}))
vi.mock('@/i18n', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
afterEach(cleanup)

it('creates a view of the selected UUIDs and refreshes the actual sketch selector', async () => {
  create.mockResolvedValue({ id: 'new-view', title: 'Work' })
  const client = new QueryClient()
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  render(
    <QueryClientProvider client={client}>
      <NewSketch selection={{ nodeIds: ['alice', 'company'], edgeIds: ['employment'] }}>
        <button>Sketch from selection</button>
      </NewSketch>
    </QueryClientProvider>
  )
  fireEvent.click(screen.getByRole('button', { name: 'Sketch from selection' }))
  fireEvent.change(screen.getByRole('textbox', { name: 'Sketch name' }), {
    target: { value: 'Work' }
  })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(create).toHaveBeenCalledOnce())
  expect(JSON.parse(create.mock.calls[0][0])).toEqual({
    title: 'Work',
    description: '',
    investigation_id: 'case',
    node_ids: ['alice', 'company'],
    edge_ids: ['employment']
  })
  await waitFor(() =>
    expect(navigate).toHaveBeenCalledWith({
      to: '/dashboard/investigations/case/graph/new-view'
    })
  )
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['dashboard', 'investigation', 'case'] })
})
