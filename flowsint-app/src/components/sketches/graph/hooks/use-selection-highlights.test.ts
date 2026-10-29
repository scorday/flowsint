// @vitest-environment jsdom
import { cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import type { GraphEdge } from '@/types'
import { useSelectionHighlights } from './use-selection-highlights'

afterEach(cleanup)

const edge = (source: string, target: string): GraphEdge =>
  ({ id: `${source}-${target}`, source, target, label: 'FRIEND_OF' }) as GraphEdge

const edges = [
  edge('root', 'alice'),
  edge('root', 'bob'),
  edge('alice', 'bob'),
  edge('bob', 'alice'),
  edge('alice', 'second-hop'),
  edge('second-hop', 'outside')
]
const neighborhood = new Set(['root', 'alice', 'bob'])
const rootLinks = new Set(['root-alice', 'root-bob'])

it('toggles links inside the highlighted neighborhood without expanding to second-hop nodes', () => {
  const { result, rerender } = renderHook(
    ({ enabled }) =>
      useSelectionHighlights(neighborhood, rootLinks, new Set(['root']), edges, enabled),
    { initialProps: { enabled: false } }
  )
  expect(result.current.highlightLinks).toEqual(rootLinks)

  rerender({ enabled: true })
  expect(result.current.highlightNodes).toEqual(neighborhood)
  expect(result.current.highlightLinks).toEqual(
    new Set(['root-alice', 'root-bob', 'alice-bob', 'bob-alice'])
  )

  rerender({ enabled: false })
  expect(result.current.highlightNodes).toBe(neighborhood)
  expect(result.current.highlightLinks).toBe(rootLinks)
})

it('updates links when manual selection or visible edges change and clears with selection', () => {
  const nodes = new Set<string>()
  const links = new Set<string>()
  const { result, rerender } = renderHook(
    ({ selected, visibleEdges }) =>
      useSelectionHighlights(nodes, links, new Set(selected), visibleEdges, true),
    { initialProps: { selected: ['alice', 'bob'], visibleEdges: edges } }
  )
  expect(result.current.highlightLinks).toEqual(new Set(['alice-bob', 'bob-alice']))

  rerender({ selected: ['alice', 'second-hop'], visibleEdges: edges })
  expect(result.current.highlightLinks).toEqual(new Set(['alice-second-hop']))

  rerender({ selected: ['alice', 'second-hop'], visibleEdges: [] })
  expect(result.current.highlightLinks.size).toBe(0)

  rerender({ selected: [], visibleEdges: edges })
  expect(result.current.highlightNodes.size).toBe(0)
  expect(result.current.highlightLinks.size).toBe(0)
})

it('handles endpoints resolved to node objects by the graph renderer and preserves path links', () => {
  const resolved = {
    ...edge('alice', 'bob'),
    source: { id: 'alice' },
    target: { id: 'bob' }
  } as unknown as GraphEdge
  const { result } = renderHook(() =>
    useSelectionHighlights(
      new Set(['alice', 'bob']),
      new Set(['path-link']),
      new Set(),
      [resolved],
      true
    )
  )
  expect(result.current.highlightLinks).toEqual(new Set(['path-link', 'alice-bob']))
})
