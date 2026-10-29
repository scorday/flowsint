import { expect, it } from 'vitest'
import type { GraphEdge, GraphNode } from '@/types'
import { getNeighborhoodView } from './neighborhood-view'

const nodes = ['root', 'alice', 'bob', 'second-hop', 'outside', 'isolated'].map(
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
  edge('alice-bob', 'alice', 'bob'),
  edge('parallel', 'alice', 'bob'),
  edge('reverse', 'bob', 'alice'),
  edge('second', 'alice', 'second-hop'),
  edge('outside', 'second-hop', 'outside')
]

it.each<[boolean, boolean, string[], string[]]>([
  [false, false, nodes.map((n) => n.id), edges.map((e) => e.id)],
  [false, true, nodes.map((n) => n.id), ['alice-bob', 'parallel', 'reverse']],
  [
    true,
    false,
    ['root', 'alice', 'bob'],
    ['root-alice', 'bob-root', 'alice-bob', 'parallel', 'reverse']
  ],
  [true, true, ['root', 'alice', 'bob'], ['alice-bob', 'parallel', 'reverse']]
])('combines neighborhood=%s and hidden root links=%s', (only, hide, nodeIds, edgeIds) => {
  const result = getNeighborhoodView(nodes, edges, 'root', only, hide)
  expect(result.nodes.map((n) => n.id)).toEqual(nodeIds)
  expect(result.edges.map((e) => e.id)).toEqual(edgeIds)
})

it.each([null, 'removed-root'])('keeps the full graph when root is %s', (root) => {
  const result = getNeighborhoodView(nodes, edges, root, true, true)
  expect(result.active).toBe(false)
  expect(result.nodes).toBe(nodes)
  expect(result.edges).toBe(edges)
})

it('keeps an isolated root and recalculates the neighborhood when the root changes', () => {
  const isolated = getNeighborhoodView(nodes, edges, 'isolated', true, true)
  expect(isolated.nodes.map((n) => n.id)).toEqual(['isolated'])
  expect(isolated.edges).toEqual([])
  const changed = getNeighborhoodView(nodes, edges, 'alice', true, false)
  expect(changed.nodes.map((n) => n.id)).toEqual(['root', 'alice', 'bob', 'second-hop'])
  expect(changed.edges.map((e) => e.id)).not.toContain('outside')
})

it('supports renderer-resolved endpoints, excludes missing nodes, and never edits the source graph', () => {
  const resolved = edges.map((e) => ({
    ...e,
    source: { id: e.source },
    target: { id: e.target }
  })) as unknown as GraphEdge[]
  resolved.push(edge('missing', 'root', 'missing'))
  const before = JSON.stringify({ nodes, edges: resolved })
  const result = getNeighborhoodView(nodes, resolved, 'root', true, false)
  expect(result.nodes.map((n) => n.id)).toEqual(['root', 'alice', 'bob'])
  expect(result.edges.map((e) => e.id)).not.toContain('missing')
  expect(result.nodes[0]).toBe(nodes[0])
  expect(JSON.stringify({ nodes, edges: resolved })).toBe(before)
  const restored = getNeighborhoodView(nodes, resolved, 'root', false, false)
  expect(restored.nodes).toBe(nodes)
  expect(restored.edges).toBe(resolved)
})
