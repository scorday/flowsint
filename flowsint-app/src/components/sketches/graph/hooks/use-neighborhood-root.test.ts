// @vitest-environment jsdom
import { cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { useNeighborhoodRoot } from './use-neighborhood-root'

afterEach(cleanup)

it('keeps the root after deselection, follows another selected root, and releases when disabled', () => {
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
  expect(result.current).toBe('friend')
  rerender({ current: null, enabled: true })
  expect(result.current).toBe('friend')
  rerender({ current: null, enabled: false })
  expect(result.current).toBeNull()
  rerender({ current: null, enabled: true })
  expect(result.current).toBeNull()
})

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
