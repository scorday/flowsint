import { useGraphStore } from '@/stores/graph-store'
import { useFlowStore } from '@/stores/flow-store'
import { useChatState } from '@/stores/use-chat-store'
import { useAnalysisPanelStore } from '@/stores/analysis-panel-store'
import { useGraphControls } from '@/stores/graph-controls-store'
import { useGraphSaveStatus } from '@/stores/graph-save-status-store'
import { useLayoutStore } from '@/stores/layout-store'
import { useGraphSettingsStore } from '@/stores/graph-settings-store'
import { toast } from 'sonner'

export function resetProjectState() {
  useGraphStore.setState(useGraphStore.getInitialState(), true)
  useFlowStore.setState(useFlowStore.getInitialState(), true)
  useChatState.setState(useChatState.getInitialState(), true)
  useAnalysisPanelStore.setState(useAnalysisPanelStore.getInitialState(), true)
  useGraphControls.setState(useGraphControls.getInitialState(), true)
  useGraphSaveStatus.setState(useGraphSaveStatus.getInitialState(), true)
  useGraphSettingsStore.setState({
    settingsModalOpen: false,
    keyboardShortcutsOpen: false,
    importModalOpen: false
  })
  useLayoutStore.setState({
    isOpenAnalysis: false,
    isOpenDetails: false,
    isOpenChat: false,
    isOpenConsole: false
  })
  toast.dismiss()
}
