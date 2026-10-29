import { create } from 'zustand'

export type ExplorationRequest = {
  sketchId: string
  rootId?: string
  targetId?: string
  mode: 'path' | 'neighborhood'
  depth?: number
  autoRun?: boolean
}

// Ephemeral UI request, never persisted across sketches or browser sessions.
export const useGraphExploration = create<{
  request: (ExplorationRequest & { token: number }) | null
  open: (request: ExplorationRequest) => void
  close: () => void
}>((set) => ({
  request: null,
  open: (request) =>
    set((state) => ({ request: { ...request, token: (state.request?.token ?? 0) + 1 } })),
  close: () => set({ request: null })
}))
