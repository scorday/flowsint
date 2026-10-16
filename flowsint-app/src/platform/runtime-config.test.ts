// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createRuntimeConfig, startFrontend } from './vendor/runtime-config'

const envelope = () => ({
  version: 1,
  application: 'flowsint-ui',
  profile: 'local',
  domain: 'avl4.localhost',
  settings: {
    apiBaseUrl: '/',
    assetBaseUrl: '/',
    homeUrl: '/',
    loginUrl: '/auth/login',
    logoutUrl: '/auth/logout',
    adminUrl: '/',
    storageBaseUrl: '/d',
    panelCssUrl: '/panel/index.css',
    panelJsUrl: '/panel/index.js',
    cookieDomain: '.avl4.localhost',
    cardsPrefix: '/web',
    mode: 'base',
    authBypass: false
  }
})
beforeEach(() => {
  document.head.innerHTML = ''
  document.body.innerHTML = '<div id="main_panel"></div><div id="root"></div>'
})

describe('Flowsint runtime startup', () => {
  it('validates config before app import and mounts exactly one external panel', async () => {
    const fetcher = vi.fn<typeof fetch>(
      async () =>
        new Response(JSON.stringify(envelope()), {
          headers: { 'content-type': 'application/json' }
        })
    )
    const loader = createRuntimeConfig({
      application: 'flowsint-ui',
      url: new URL('https://avl4.localhost/runtime-config.json'),
      runtime: true,
      fetcher
    })
    const loadApp = vi.fn(async () => {
      expect(loader.get().apiBaseUrl).toBe('/')
      expect(document.querySelector('#avl4-panel-script')).toBeTruthy()
    })
    await startFrontend({ loader, rootId: 'root', panel: true, loadApp })
    await startFrontend({ loader, rootId: 'root', panel: true, loadApp })
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher.mock.calls[0]?.[1]).toMatchObject({
      credentials: 'omit',
      cache: 'no-store',
      redirect: 'error'
    })
    expect(document.querySelectorAll('#avl4-panel-script')).toHaveLength(1)
  })

  it.each(['invalid', 'network', 'wrong-application', 'bypass'])(
    'fails closed on %s runtime config',
    async (kind) => {
      const value = envelope()
      if (kind === 'wrong-application') value.application = 'monitoring'
      if (kind === 'bypass') value.settings.authBypass = true
      const loader = createRuntimeConfig({
        application: 'flowsint-ui',
        url: new URL('https://avl4.localhost/runtime-config.json'),
        runtime: true,
        fetcher: async () => {
          if (kind === 'network') throw new Error('private detail')
          return new Response(kind === 'invalid' ? 'invalid' : JSON.stringify(value), {
            headers: { 'content-type': 'application/json' }
          })
        }
      })
      const loadApp = vi.fn()
      await startFrontend({ loader, rootId: 'root', panel: true, loadApp })
      expect(loadApp).not.toHaveBeenCalled()
      expect(document.querySelector('#avl4-panel-script')).toBeNull()
      expect(document.querySelector('[role="alert"]')?.textContent).toBe(
        'Не удалось загрузить приложение. Обновите страницу.'
      )
    }
  )
})
