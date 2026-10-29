import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type ViewType = 'graph' | 'table' | 'map' | 'relationships'
type LayoutType = 'force' | 'hierarchy'
type SelectionMode = 'lasso' | 'rectangle'
type NeighborhoodRoot = { graphId?: string; nodeId: string } | null

type GraphControlsStore = {
  view: ViewType
  isSelectorModeActive: boolean
  selectionMode: SelectionMode
  highlightSelectionLinks: boolean
  setHighlightSelectionLinks: (enabled: boolean) => void
  hideRootAndIsolated: boolean
  setHideRootAndIsolated: (enabled: boolean) => void
  neighborhoodRoot: NeighborhoodRoot
  setNeighborhoodRoot: (root: NeighborhoodRoot) => void
  currentLayoutType: LayoutType
  zoomToFit: () => void
  zoomIn: () => void
  zoomOut: () => void
  zoomToSelection: () => void
  centerOnNode: (x: number, y: number) => void
  onLayout: (layout: any) => void
  setActions: (actions: Partial<GraphControlsStore>) => void
  refetchGraph: (onSuccess?: () => void) => void
  regenerateLayout: (layoutType: LayoutType) => void
  getViewportCenter: () => { x: number; y: number } | null
  setCurrentLayoutType: (layoutType: LayoutType) => void
  setView: (view: 'graph' | 'table' | 'map' | 'relationships') => void
  setIsSelectorModeActive: (active: boolean) => void
  setSelectionMode: (mode: SelectionMode) => void
}

export const useGraphControls = create<GraphControlsStore>()(
  persist(
    (set) => ({
      view: 'graph',
      isSelectorModeActive: false,
      selectionMode: 'lasso',
      highlightSelectionLinks: false,
      setHighlightSelectionLinks: (enabled) => set({ highlightSelectionLinks: enabled }),
      hideRootAndIsolated: false,
      setHideRootAndIsolated: (enabled) =>
        set((state) => ({
          hideRootAndIsolated: enabled,
          neighborhoodRoot: enabled ? state.neighborhoodRoot : null
        })),
      neighborhoodRoot: null,
      setNeighborhoodRoot: (root) => set({ neighborhoodRoot: root }),
      currentLayoutType: 'force',
      zoomToFit: () => {},
      zoomIn: () => {},
      zoomOut: () => {},
      zoomToSelection: () => {},
      centerOnNode: () => {},
      onLayout: () => {},
      setActions: (actions) => set(actions),
      refetchGraph: (_onSuccess) => {},
      regenerateLayout: () => {},
      getViewportCenter: () => null,
      setCurrentLayoutType: (layoutType) => set({ currentLayoutType: layoutType }),
      setView: (view) => set({ view }),
      setIsSelectorModeActive: (active) => set({ isSelectorModeActive: active }),
      setSelectionMode: (mode) => set({ selectionMode: mode })
    }),
    {
      name: 'graph-controls-storage',
      version: 1,
      migrate: (persistedState) => {
        const { hideRootLinks, onlyRootNeighborhood, ...settings } =
          persistedState as Partial<GraphControlsStore> & {
            hideRootLinks?: boolean
            onlyRootNeighborhood?: boolean
          }
        return {
          view: settings.view ?? 'graph',
          currentLayoutType: settings.currentLayoutType ?? 'force',
          selectionMode: settings.selectionMode ?? 'lasso',
          highlightSelectionLinks: settings.highlightSelectionLinks ?? false,
          hideRootAndIsolated: Boolean(hideRootLinks || onlyRootNeighborhood)
        }
      },
      partialize: (state) => ({
        view: state.view,
        currentLayoutType: state.currentLayoutType,
        selectionMode: state.selectionMode,
        highlightSelectionLinks: state.highlightSelectionLinks,
        hideRootAndIsolated: state.hideRootAndIsolated
      })
    }
  )
)
