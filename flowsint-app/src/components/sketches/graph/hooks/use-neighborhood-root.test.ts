// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useNeighborhoodRoot } from './use-neighborhood-root'
import { useGraphControls } from '@/stores/graph-controls-store'

vi.hoisted(() => {
  const storage = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key)
  })
})
beforeEach(() => useGraphControls.setState({ neighborhoodRoot: null }))
afterEach(() => {
  cleanup()
  useGraphControls.setState({ neighborhoodRoot: null })
})

it('keeps the pinned root during inspection and changes it only through an explicit action', () => {
  const { result, rerender } = renderHook(
    ({ current, enabled }: { current: string | null; enabled: boolean }) =>
      useNeighborhoodRoot(current, enabled, 'graph'),
    { initialProps: { current: 'root' as string | null, enabled: false } }
  )
  expect(result.current).toBeNull()
  rerender({ current: 'root', enabled: true })
  expect(result.current).toBe('root')
  rerender({ current: null, enabled: true })
  expect(result.current).toBe('root')
  rerender({ current: 'friend', enabled: true })
  expect(result.current).toBe('root')
  rerender({ current: null, enabled: true })
  expect(result.current).toBe('root')
  act(() => useGraphControls.getState().setNeighborhoodRoot({ graphId: 'graph', nodeId: 'friend' }))
  expect(result.current).toBe('friend')
  rerender({ current: 'root', enabled: true })
  expect(result.current).toBe('friend')
  rerender({ current: null, enabled: false })
  expect(result.current).toBeNull()
  rerender({ current: null, enabled: true })
  expect(result.current).toBeNull()
})

it('allows a secondary preview without releasing the main graph root', () => {
  const anchor = { graphId: 'main', nodeId: 'root' }
  useGraphControls.getState().setNeighborhoodRoot(anchor)
  const { result } = renderHook(() => useNeighborhoodRoot(null, false, 'neighbors', false))
  expect(result.current).toBeNull()
  expect(useGraphControls.getState().neighborhoodRoot).toBe(anchor)
})

it('releases the root when the filter is disabled and never persists node IDs', () => {
  const store = useGraphControls.getState()
  store.setHideRootAndIsolated(true)
  store.setNeighborhoodRoot({ graphId: 'main', nodeId: 'root' })
  expect(useGraphControls.getState().neighborhoodRoot?.nodeId).toBe('root')
  expect(
    useGraphControls.persist.getOptions().partialize!(useGraphControls.getState())
  ).not.toHaveProperty('neighborhoodRoot')
  store.setHideRootAndIsolated(false)
  expect(useGraphControls.getState().neighborhoodRoot).toBeNull()
})

it.each([
  [false, false],
  [true, false],
  [false, true],
  [true, true]
])(
  'migrates saved filters only=%s hide=%s to the unified mode',
  async (onlyRootNeighborhood, hideRootLinks) => {
    const migrated = await useGraphControls.persist.getOptions().migrate!(
      { onlyRootNeighborhood, hideRootLinks, view: 'table', highlightSelectionLinks: true },
      0
    )
    expect(migrated).toEqual({
      view: 'table',
      currentLayoutType: 'force',
      selectionMode: 'lasso',
      highlightSelectionLinks: true,
      hideRootAndIsolated: onlyRootNeighborhood || hideRootLinks
    })
  }
)

it('never carries a retained root into another graph or reuses it when returning', () => {
  const { result, rerender } = renderHook(
    ({ current, graph }: { current: string | null; graph: string }) =>
      useNeighborhoodRoot(current, true, graph),
    { initialProps: { current: 'root' as string | null, graph: 'first' } }
  )
  rerender({ current: null, graph: 'first' })
  expect(result.current).toBe('root')
  rerender({ current: null, graph: 'second' })
  expect(result.current).toBeNull()
  rerender({ current: null, graph: 'first' })
  expect(result.current).toBeNull()
})
