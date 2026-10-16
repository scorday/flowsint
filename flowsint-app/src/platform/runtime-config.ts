import { createRuntimeConfig } from './vendor/runtime-config'

const mode = import.meta.env.VITE_AUTH_MODE ?? 'standalone'
if (mode !== 'standalone' && mode !== 'avl4') throw new Error('Invalid authentication mode')
export const isAvl4 = mode === 'avl4'

export const runtimeConfig = createRuntimeConfig({
  application: 'flowsint-ui',
  url: new URL(
    '/runtime-config.json',
    typeof window === 'undefined' ? 'https://runtime.invalid' : window.location.origin
  ),
  runtime: isAvl4 && import.meta.env.VITE_RUNTIME_CONFIG === 'true',
  legacy:
    import.meta.env.VITE_RUNTIME_CONFIG === 'true'
      ? undefined
      : {
          ...import.meta.env,
          VITE_BASE_API_URL:
            import.meta.env.VITE_BASE_API_URL ?? import.meta.env.VITE_API_URL ?? '/'
        }
})

export const getApiBaseUrl = () =>
  isAvl4 ? runtimeConfig.get().apiBaseUrl : (import.meta.env.VITE_API_URL ?? '')
