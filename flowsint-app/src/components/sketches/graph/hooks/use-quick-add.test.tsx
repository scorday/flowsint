// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useQuickAdd } from './use-quick-add'

const mocks = vi.hoisted(() => ({ detect: vi.fn(), add: vi.fn() }))
vi.mock('@/api/sketch-service', () => ({ sketchService: { detectType: mocks.detect } }))
// Simulate Enter before the debounced preview has run.
vi.mock('@/hooks/use-debounce', () => ({ useDebounce: () => '' }))
vi.mock('../../use-manual-node-add', () => ({ useManualNodeAdd: () => ({ add: mocks.add }) }))
vi.mock('@/i18n', () => ({ useTranslation: () => ({ t: (value: string) => value }) }))
vi.mock('sonner', () => ({ toast: { error: vi.fn() } }))
beforeEach(() => {
  vi.clearAllMocks()
  mocks.detect.mockResolvedValue({
    type: 'Email',
    fields: [{ primary: true, name: 'email', value: 'a@example.com' }]
  })
  mocks.add.mockResolvedValue(undefined)
})
afterEach(cleanup)

function open() {
  const hook = renderHook(() => useQuickAdd('view-b'))
  act(() => hook.result.current.openQuickAdd(10, 20, 30, 40))
  act(() => hook.result.current.setQuickAddText('a@example.com'))
  return hook
}

it('checks the submitted type before invoking shared matching, and restores input on cancel', async () => {
  const { result } = open()
  await act(() => result.current.submitQuickAdd())
  expect(mocks.detect).toHaveBeenCalledWith('a@example.com')
  expect(mocks.add.mock.calls[0][0]).toMatchObject({
    nodeType: 'email',
    nodeProperties: { email: 'a@example.com' },
    x: 30,
    y: 40
  })
  expect(result.current.quickAdd.active).toBe(false)
  act(() => mocks.add.mock.calls[0][1].onCancel())
  expect(result.current.quickAdd.active).toBe(true)
  expect(result.current.quickAdd.text).toBe('a@example.com')
})

it('keeps the input and does not create an incorrectly typed object on detection failure', async () => {
  mocks.detect.mockRejectedValue(new Error('offline'))
  const { result } = open()
  await act(() => result.current.submitQuickAdd())
  expect(mocks.add).not.toHaveBeenCalled()
  expect(result.current.quickAdd.text).toBe('a@example.com')
  expect(result.current.quickAdd.active).toBe(true)
})
