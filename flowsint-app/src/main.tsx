import { startFrontend } from './platform/vendor/runtime-config'
import { isAvl4, runtimeConfig } from './platform/runtime-config'

if (isAvl4) document.documentElement.dataset.platform = 'avl4'

export const startup = startFrontend({
  loader: runtimeConfig,
  rootId: 'root',
  panel: isAvl4,
  loadApp: () => import('./mount')
})
