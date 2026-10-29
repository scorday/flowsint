import { expect, it } from 'vitest'
import type { GraphEdge, GraphNode } from '@/types'
import { getNeighborhoodView } from './neighborhood-view'

const nodes = ['root', 'alice', 'bob', 'second-hop', 'outside', 'leaf', 'isolated'].map(
  (id, x): GraphNode => ({
    id,
    nodeLabel: id,
    nodeType: 'socialaccount',
    nodeProperties: { original: id },
    nodeMetadata: {},
    nodeColor: null,
    nodeIcon: null,
    nodeImage: null,
    nodeFlag: null,
    nodeShape: null,
    nodeSize: 4,
    x,
    y: x
  })
)
const edge = (id: string, source: string, target: string): GraphEdge => ({
  id,
  source,
  target,
  label: 'FRIEND_OF'
})
const edges = [
  edge('root-alice', 'root', 'alice'),
  edge('bob-root', 'bob', 'root'),
  edge('root-leaf', 'root', 'leaf'),
  edge('alice-bob', 'alice', 'bob'),
  edge('parallel', 'alice', 'bob'),
  edge('reverse', 'bob', 'alice'),
  edge('second', 'alice', 'second-hop'),
  edge('outside', 'second-hop', 'outside')
]

it('hides the root, its links and isolated nodes while preserving connected nodes at any depth', () => {
  const result = getNeighborhoodView(nodes, edges, 'root', true)
  expect(result.active).toBe(true)
  expect(result.nodes.map((n) => n.id)).toEqual(['alice', 'bob', 'second-hop', 'outside'])
  expect(result.edges.map((e) => e.id)).toEqual([
    'alice-bob',
    'parallel',
    'reverse',
    'second',
    'outside'
  ])
})

it('keeps the full graph when the filter is disabled', () => {
  const result = getNeighborhoodView(nodes, edges, 'root', false)
  expect(result.active).toBe(false)
  expect(result.nodes).toBe(nodes)
  expect(result.edges).toBe(edges)
})

it.each([null, 'removed-root'])('keeps the full graph when root is %s', (root) => {
  const result = getNeighborhoodView(nodes, edges, root, true)
  expect(result.active).toBe(false)
  expect(result.nodes).toBe(nodes)
  expect(result.edges).toBe(edges)
})

it('hides an isolated root and recalculates remaining connections when the root changes', () => {
  const isolated = getNeighborhoodView(nodes, edges, 'isolated', true)
  expect(isolated.nodes.map((n) => n.id)).toEqual(
    nodes.filter((n) => n.id !== 'isolated').map((n) => n.id)
  )
  expect(isolated.edges).toEqual(edges)
  const changed = getNeighborhoodView(nodes, edges, 'alice', true)
  expect(changed.nodes.map((n) => n.id)).toEqual(['root', 'bob', 'second-hop', 'outside', 'leaf'])
  expect(changed.edges.map((e) => e.id)).toEqual(['bob-root', 'root-leaf', 'outside'])
})

it('can hide the entire graph when all remaining nodes lose their only link', () => {
  const result = getNeighborhoodView(nodes, [edge('root-leaf', 'root', 'leaf')], 'root', true)
  expect(result).toEqual({ nodes: [], edges: [], active: true })
})

it('supports renderer-resolved endpoints, excludes missing nodes, and never edits the source graph', () => {
  const resolved = edges.map((e) => ({
    ...e,
    source: { id: e.source },
    target: { id: e.target }
  })) as unknown as GraphEdge[]
  resolved.push(edge('missing', 'root', 'missing'))
  resolved.push(edge('dangling', 'isolated', 'missing'))
  const before = JSON.stringify({ nodes, edges: resolved })
  const result = getNeighborhoodView(nodes, resolved, 'root', true)
  expect(result.nodes.map((n) => n.id)).toEqual(['alice', 'bob', 'second-hop', 'outside'])
  expect(result.edges.map((e) => e.id)).toEqual([
    'alice-bob',
    'parallel',
    'reverse',
    'second',
    'outside'
  ])
  expect(result.nodes[0]).toBe(nodes[1])
  expect(JSON.stringify({ nodes, edges: resolved })).toBe(before)
  const restored = getNeighborhoodView(nodes, resolved, 'root', false)
  expect(restored.nodes).toBe(nodes)
  expect(restored.edges).toBe(resolved)
})
