import { fetchWithAuth } from './api'
import type {
  Sketch,
  SketchGraphData,
  DetectionResult,
  EntityMapping,
  PreviewEdge,
  ImportAnalysisResult,
  ImportExecutionResult,
  RelationshipType
} from '@/types'
import type { GraphNode } from '@/types/graph'
import type { ActionItem } from '@/lib/action-items'

export type NodeMatch = {
  node: GraphNode
  match: 'exact' | 'possible'
  on_sketch: boolean
}

export type GraphObject = Pick<GraphNode, 'id' | 'nodeLabel' | 'nodeType'> & { on_sketch: boolean }
export type ExplorationOptions = {
  mode: 'path' | 'neighborhood'
  root_id: string
  target_id?: string
  depth: number
  node_types: string[]
  edge_types: string[]
  directed: boolean
}
export type GraphExploration = SketchGraphData & {
  paths: { node_ids: string[]; edge_ids: string[] }[]
  distances: Record<string, number>
  on_sketch: string[]
  edge_views: Record<string, string[]>
  truncated: boolean
  depth: number
  limits: { nodes: number; edges: number; paths: number; scanned: number }
}
export type ExplorationKind = 'nodes' | 'edges' | 'paths'
export type ExplorationJob = {
  id: string
  status: 'queued' | 'running' | 'completed' | 'cancelled' | 'failed' | 'applying' | 'applied'
  revision: number
  totals: Record<ExplorationKind, number>
  selected: Record<ExplorationKind, number>
  options: ExplorationOptions
  sketch_id?: string
  error?: string
  updated_at: number
  stalled?: boolean
}
export type ExplorationNode = GraphObject & { distance: number; selected: boolean }
export type ExplorationEdge = {
  id: string
  source: string
  target: string
  label: string
  sourceLabel: string
  targetLabel: string
  views: string[]
  selected: boolean
}
export type ExplorationPath = {
  id: string
  node_ids: string[]
  edge_ids: string[]
  nodes: ExplorationNode[]
  edges: ExplorationEdge[]
  selected: boolean
}
export type ExplorationRow = ExplorationNode | ExplorationEdge | ExplorationPath
export type ExplorationPage = ExplorationJob & {
  items: ExplorationRow[]
  page: number
  size: number
}

export type ExplorationCatalog = {
  node_types: string[]
  edge_types: string[]
  sketches: { id: string; title: string }[]
  truncated: boolean
}

// `inline=true` asks the backend for the relationships-already-joined
// shape (used by the flat table view) instead of the default {nds, rls}
// graph slice — the response shape genuinely depends on that flag, hence
// the overload rather than a single loosely-typed union return.
async function getGraphDataById(sketchId: string, inline: true): Promise<RelationshipType[]>
async function getGraphDataById(sketchId: string, inline?: false): Promise<SketchGraphData>
async function getGraphDataById(
  sketchId: string,
  inline: boolean = false
): Promise<SketchGraphData | RelationshipType[]> {
  if (inline)
    return fetchWithAuth(`/api/sketches/${sketchId}/graph?format=inline`, { method: 'GET' })
  const graph: SketchGraphData = { nds: [], rls: [] }
  let revision: number | undefined
  for (const kind of ['nodes', 'edges']) {
    let after = ''
    let more = true
    while (more) {
      const params = new URLSearchParams({ kind, after, size: '1000' })
      if (revision !== undefined) params.set('revision', String(revision))
      const page: SketchGraphData & { after: string; has_more: boolean; revision: number } =
        await fetchWithAuth(`/api/sketches/${sketchId}/graph/page?${params}`)
      graph.nds.push(...page.nds)
      graph.rls.push(...page.rls)
      after = page.after
      more = page.has_more
      revision = page.revision
    }
  }
  return graph
}

export const sketchService = {
  get: async (): Promise<Sketch[]> => {
    return fetchWithAuth('/api/sketches', {
      method: 'GET'
    })
  },
  getById: async (sketchId: string): Promise<Sketch> => {
    return fetchWithAuth(`/api/sketches/${sketchId}`, {
      method: 'GET'
    })
  },
  getGraphDataById,
  searchGraphObjects: (
    sketchId: string,
    query: string,
    ids: string[] = [],
    signal?: AbortSignal
  ): Promise<{ nodes: GraphObject[]; has_more: boolean }> =>
    fetchWithAuth(`/api/sketches/${sketchId}/investigation-objects/search`, {
      method: 'POST',
      body: JSON.stringify({ query, ids }),
      signal
    }),
  explorationCatalog: (sketchId: string, signal?: AbortSignal): Promise<ExplorationCatalog> =>
    fetchWithAuth(`/api/sketches/${sketchId}/exploration/catalog`, { signal }),
  explore: (
    sketchId: string,
    options: ExplorationOptions,
    signal?: AbortSignal
  ): Promise<GraphExploration> =>
    fetchWithAuth(`/api/sketches/${sketchId}/exploration`, {
      method: 'POST',
      body: JSON.stringify(options),
      signal
    }),
  startExploration: (sketchId: string, options: ExplorationOptions): Promise<ExplorationJob> =>
    fetchWithAuth(`/api/sketches/${sketchId}/exploration/jobs`, {
      method: 'POST',
      body: JSON.stringify(options)
    }),
  explorationStatus: (
    sketchId: string,
    jobId: string,
    signal?: AbortSignal
  ): Promise<ExplorationJob> =>
    fetchWithAuth(`/api/sketches/${sketchId}/exploration/jobs/${jobId}`, { signal }),
  explorationPage: (
    sketchId: string,
    jobId: string,
    kind: ExplorationKind,
    page: number,
    signal?: AbortSignal
  ): Promise<ExplorationPage> =>
    fetchWithAuth(
      `/api/sketches/${sketchId}/exploration/jobs/${jobId}/page?kind=${kind}&page=${page}&size=50`,
      { signal }
    ),
  selectExploration: (
    sketchId: string,
    jobId: string,
    data: {
      kind: ExplorationKind | 'all'
      checked: boolean
      ids: string[] | null
      revision: number
    }
  ): Promise<ExplorationJob> =>
    fetchWithAuth(`/api/sketches/${sketchId}/exploration/jobs/${jobId}/selection`, {
      method: 'POST',
      body: JSON.stringify(data)
    }),
  cancelExploration: (sketchId: string, jobId: string): Promise<ExplorationJob> =>
    fetchWithAuth(`/api/sketches/${sketchId}/exploration/jobs/${jobId}/cancel`, { method: 'POST' }),
  applyExploration: (
    sketchId: string,
    jobId: string,
    data: {
      action: 'create' | 'attach'
      title?: string
      revision: number
    }
  ): Promise<ExplorationJob> =>
    fetchWithAuth(`/api/sketches/${sketchId}/exploration/jobs/${jobId}/apply`, {
      method: 'POST',
      body: JSON.stringify(data)
    }),
  findNodeMatches: async (sketchId: string, node: GraphNode): Promise<NodeMatch[]> =>
    fetchWithAuth(`/api/sketches/${sketchId}/nodes/matches`, {
      method: 'POST',
      body: JSON.stringify(node)
    }),
  getInvestigationGraph: async (sketchId: string): Promise<SketchGraphData> =>
    fetchWithAuth(`/api/sketches/${sketchId}/investigation-graph`, { method: 'GET' }),
  attachSubgraph: async (
    sketchId: string,
    nodeIds: string[],
    edgeIds: string[]
  ): Promise<unknown> =>
    fetchWithAuth(`/api/sketches/${sketchId}/subgraph`, {
      method: 'POST',
      body: JSON.stringify({ node_ids: nodeIds, edge_ids: edgeIds })
    }),
  deleteFromInvestigation: async (
    sketchId: string,
    nodeIds: string[],
    edgeIds: string[]
  ): Promise<unknown> =>
    fetchWithAuth(`/api/sketches/${sketchId}/investigation-elements`, {
      method: 'DELETE',
      body: JSON.stringify({ node_ids: nodeIds, edge_ids: edgeIds })
    }),
  // Backend returns the created sketch on success, or an { error } payload
  // instead of a 4xx/5xx status on failure — callers branch on `id`.
  create: async (body: BodyInit): Promise<Sketch | { error: string }> => {
    return fetchWithAuth(`/api/sketches/create`, {
      method: 'POST',
      body: body
    })
  },
  delete: async (sketchId: string): Promise<unknown> => {
    return fetchWithAuth(`/api/sketches/${sketchId}`, {
      method: 'DELETE'
    })
  },
  addNode: async (sketchId: string, body: BodyInit): Promise<{ node: GraphNode }> => {
    return fetchWithAuth(`/api/sketches/${sketchId}/nodes/add`, {
      method: 'POST',
      body: body
    })
  },
  addEdge: async (sketchId: string, body: BodyInit): Promise<unknown> => {
    return fetchWithAuth(`/api/sketches/${sketchId}/relations/add`, {
      method: 'POST',
      body: body
    })
  },
  mergeNodes: async (sketchId: string, body: BodyInit): Promise<unknown> => {
    return fetchWithAuth(`/api/sketches/${sketchId}/nodes/merge`, {
      method: 'POST',
      body: body
    })
  },
  deleteNodes: async (sketchId: string, body: BodyInit): Promise<unknown> => {
    return fetchWithAuth(`/api/sketches/${sketchId}/nodes`, {
      method: 'DELETE',
      body: body
    })
  },
  deleteEdges: async (sketchId: string, body: BodyInit): Promise<unknown> => {
    return fetchWithAuth(`/api/sketches/${sketchId}/relationships`, {
      method: 'DELETE',
      body: body
    })
  },
  updateNode: async (sketchId: string, body: BodyInit): Promise<{ status: string }> => {
    return fetchWithAuth(`/api/sketches/${sketchId}/nodes/edit`, {
      method: 'PUT',
      body: body
    })
  },
  updateEdge: async (sketchId: string, body: BodyInit): Promise<unknown> => {
    return fetchWithAuth(`/api/sketches/${sketchId}/relationships/edit`, {
      method: 'PUT',
      body: body
    })
  },
  getNodeNeighbors: async (sketchId: string, nodeId: string): Promise<SketchGraphData> => {
    return fetchWithAuth(`/api/sketches/${sketchId}/nodes/${nodeId}`, {
      method: 'GET'
    })
  },
  types: async (flat = false): Promise<ActionItem[]> => {
    return fetchWithAuth(`/api/types${flat ? '?flat=true' : ''}`, {
      method: 'GET'
    })
  },
  detectType: async (text: string): Promise<DetectionResult> => {
    return fetchWithAuth(`/api/types/detect`, {
      method: 'POST',
      body: JSON.stringify({ text })
    })
  },
  update: async (sketchId: string, body: BodyInit): Promise<Sketch> => {
    return fetchWithAuth(`/api/sketches/${sketchId}`, {
      method: 'PUT',
      body: body
    })
  },
  analyzeImportFile: async (sketchId: string, file: File): Promise<ImportAnalysisResult> => {
    const formData = new FormData()
    formData.append('file', file)

    return fetchWithAuth(`/api/sketches/${sketchId}/import/analyze`, {
      method: 'POST',
      body: formData
    })
  },
  executeImport: async (
    sketchId: string,
    entityMappings: EntityMapping[],
    edges: PreviewEdge[]
  ): Promise<ImportExecutionResult> => {
    const formData = new FormData()
    formData.append('entity_mappings_json', JSON.stringify({ nodes: entityMappings, edges: edges }))

    return fetchWithAuth(`/api/sketches/${sketchId}/import/execute`, {
      method: 'POST',
      body: formData
    })
  },
  updateNodePositions: async (
    sketchId: string,
    positions: Array<{ nodeId: string; x: number; y: number }>
  ): Promise<unknown> => {
    return fetchWithAuth(`/api/sketches/${sketchId}/nodes/positions`, {
      method: 'PUT',
      body: JSON.stringify({ positions })
    })
  },
  exportSketch: async (sketchId: string, format: 'json' = 'json'): Promise<unknown> => {
    const response = await fetchWithAuth(`/api/sketches/${sketchId}/export?format=${format}`, {
      method: 'GET'
    })

    if (format === 'json') {
      const data = await response
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `sketch-${sketchId}.json`
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
    }

    return response
  }
}
