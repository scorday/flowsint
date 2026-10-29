import React, { useEffect, useMemo, useState } from 'react'
import { useAuth, useProject } from '@avl4/core-sdk-react'
import { withProjectIdFragment } from '@avl4/core-sdk'
import { isAvl4 } from './platform/runtime-config'
import { getPlatformApp } from './platform/app'
import { resetProjectState } from './platform/reset-state'
import { rememberProjectRoute, restoredProjectRoute } from './platform/project-route'
import ReactDOM from 'react-dom/client'
import { RouterProvider, createRouter } from '@tanstack/react-router'
import {
  Provider as TanStackQueryProvider,
  getContext as getQueryContext
} from '@/integrations/tanstack-query/root-provider'
import { routeTree } from './routeTree.gen'
import './styles.css'
import { ThemeProvider } from '@/components/theme-provider'

function makeRouter(projectId?: string) {
  return createRouter({
    ...(projectId
      ? { rewrite: { output: ({ url }) => new URL(withProjectIdFragment(url.href, projectId)) } }
      : {}),
    routeTree,
    context: {
      ...getQueryContext()
    },
    defaultPreload: false,
    scrollRestoration: true,
    defaultStructuralSharing: true,
    // Keep components mounted but hidden during transitions
    // @ts-expect-error children-only wrapper doesn't match RouteComponent's expected prop signature
    defaultPendingComponent: ({ children }: { children: React.ReactNode }) => children,
    defaultPendingMs: 0
  })
}

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof makeRouter>
  }
}

let previousProject: string | undefined

function ScopedRouter() {
  const auth = useAuth()
  const project = useProject()
  const contextKey = `${auth.user!.id}:${auth.sessionEpoch}:${project.revision}`
  return <ProjectRouter key={contextKey} projectId={project.projectId!} userId={auth.user!.id} />
}

function ProjectRouter({ projectId, userId }: { projectId: string; userId: string }) {
  const [router, setRouter] = useState<ReturnType<typeof makeRouter> | null>(null)
  useEffect(() => {
    resetProjectState()
    const context = { userId, projectId }
    const restored = restoredProjectRoute(
      context,
      new URL(window.location.href),
      window.sessionStorage
    )
    if (restored || (previousProject !== undefined && previousProject !== projectId)) {
      window.history.replaceState(
        null,
        '',
        restored ?? withProjectIdFragment('/dashboard', projectId)
      )
    }
    previousProject = projectId
    rememberProjectRoute(context, window.location.pathname, window.sessionStorage)
    const nextRouter = makeRouter(projectId)
    const unsubscribe = nextRouter.subscribe('onResolved', () => {
      rememberProjectRoute(context, window.location.pathname, window.sessionStorage)
    })
    let active = true
    queueMicrotask(() => {
      if (active) setRouter(nextRouter)
    })
    return () => {
      active = false
      unsubscribe()
      nextRouter.history.destroy()
    }
  }, [projectId, userId])
  return router ? <RouterProvider router={router} /> : null
}

function Application() {
  const standaloneRouter = useMemo(() => (isAvl4 ? null : makeRouter()), [])
  if (!isAvl4) return <RouterProvider router={standaloneRouter!} />
  const PlatformProvider = getPlatformApp().Provider
  return (
    <PlatformProvider>
      <ScopedRouter />
    </PlatformProvider>
  )
}

const rootElement = document.getElementById('root')!

if (!rootElement.innerHTML) {
  const root = ReactDOM.createRoot(rootElement)

  root.render(
    <React.StrictMode>
      <ThemeProvider defaultTheme="dark" storageKey="vite-ui-theme">
        <TanStackQueryProvider>
          <Application />
        </TanStackQueryProvider>
      </ThemeProvider>
    </React.StrictMode>
  )
}
