import { beforeEach, describe, expect, it } from 'vitest'
import { rememberProjectRoute, restoredProjectRoute } from './project-route'

const context = { userId: 'alice', projectId: 'project-a' }
const graph = '/dashboard/investigations/case-a/graph/graph-a'
const url = (path = graph) => new URL(`https://flowsint.test${path}#pid=project-b`)
let values: Map<string, string>
let storage: Pick<Storage, 'getItem' | 'setItem'>
beforeEach(() => {
  values = new Map()
  storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => {
      values.set(key, value)
    }
  }
})

describe('route context across Main Panel reload', () => {
  it('clears the old graph when pid changes before a full reload', () => {
    rememberProjectRoute(context, graph, storage)
    expect(restoredProjectRoute({ ...context, projectId: 'project-b' }, url(), storage)).toBe(
      '/dashboard#pid=project-b'
    )
  })
  it('clears a route retained after another user logs in', () => {
    rememberProjectRoute(context, graph, storage)
    expect(restoredProjectRoute({ ...context, userId: 'bob' }, url(), storage)).toBe(
      '/dashboard#pid=project-a'
    )
  })
  it('preserves a reload within the same project', () => {
    rememberProjectRoute(context, graph, storage)
    expect(restoredProjectRoute(context, url(), storage)).toBeNull()
  })
  it('preserves an explicit deep link to a different graph in another project', () => {
    rememberProjectRoute(context, graph, storage)
    expect(
      restoredProjectRoute(
        { ...context, projectId: 'project-b' },
        url('/dashboard/investigations/b/graph/b'),
        storage
      )
    ).toBeNull()
  })
  it('tolerates missing and invalid storage', () => {
    expect(restoredProjectRoute(context, url(), storage)).toBeNull()
    storage.setItem('flowsint.route-context.v1', '{broken')
    expect(restoredProjectRoute(context, url(), storage)).toBeNull()
  })
  it('tolerates browser storage restrictions', () => {
    const restricted = {
      getItem: () => {
        throw new Error('blocked')
      },
      setItem: () => {
        throw new Error('blocked')
      }
    }
    expect(() => rememberProjectRoute(context, graph, restricted)).not.toThrow()
    expect(restoredProjectRoute(context, url(), restricted)).toBeNull()
  })
})
