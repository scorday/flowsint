// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import en from './locales/enrichers.en.json'
import ru from './locales/enrichers.ru.json'
import { setLanguage, translateFor } from './index'
import EnricherItem from '@/components/flows/enricher-list-item'
import { EnricherParamsSheet } from '@/components/sketches/enricher-params-sheet'
import type { Enricher } from '@/types/enricher'

vi.mock('@/hooks/use-icon', () => ({ useIcon: () => null }))
vi.mock('@/api/key-service', () => ({ keyService: { get: async () => [] } }))

beforeEach(() => {
  setLanguage('en')
  Element.prototype.scrollIntoView = vi.fn()
  Element.prototype.hasPointerCapture = vi.fn(() => false)
  Element.prototype.setPointerCapture = vi.fn()
  Element.prototype.releasePointerCapture = vi.fn()
})
afterEach(() => {
  cleanup()
  setLanguage('en')
})

it('translates all metadata entries and preserves the exact English source', () => {
  expect(Object.keys(en).sort()).toEqual(Object.keys(ru).sort())
  for (const [source, translated] of Object.entries(ru)) {
    expect(translateFor('en', source)).toBe(source)
    expect(translateFor('ru', source)).toBe(translated)
    expect(translated.trim()).not.toBe('')
    expect(translated).not.toBe(source)
  }
  expect(translateFor('ru', 'A user-authored custom template description')).toBe(
    'A user-authored custom template description'
  )
})

it('updates descriptions in memoized catalog cards without changing enricher identity', () => {
  const description = Object.keys(en).find((key) =>
    key.startsWith('Resolves a domain to IPv4 addresses')
  )!
  const enricher: Enricher = {
    id: 'dns',
    class_name: 'DomainToDnsEnricher',
    category: 'domain',
    name: 'domain_to_dns',
    module: 'flowsint_enrichers.domain.to_dns',
    documentation: null,
    description,
    inputs: { type: 'Domain', properties: [] },
    outputs: { type: 'Ip', properties: [] },
    type: 'enricher',
    required_params: false,
    params: {},
    params_schema: [],
    icon: null
  }
  render(<EnricherItem enricher={enricher} category="domain" />)
  expect(screen.getByText(description)).toBeTruthy()
  act(() => setLanguage('ru'))
  expect(screen.getByText(/^Разрешает домен в адреса IPv4/)).toBeTruthy()
  expect(screen.getByText('DomainToDnsEnricher')).toBeTruthy()
  expect(enricher.name).toBe('domain_to_dns')
  expect(enricher.description).toBe(description)
  act(() => setLanguage('en'))
  expect(screen.getByText(description)).toBeTruthy()
})

it('translates launch parameter help while preserving raw submitted parameter names and values', async () => {
  setLanguage('ru')
  const submit = vi.fn()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <EnricherParamsSheet
        pending={{
          enricherName: 'ip_to_ports',
          nodeIds: ['node-id'],
          paramsSchema: [
            {
              name: 'timeout',
              type: 'text',
              description: 'Timeout in milliseconds. Default: 1000',
              required: true,
              default: '1000'
            },
            {
              name: 'mode',
              type: 'select',
              description:
                'Scan mode: active (direct port scanning) or passive (using PDCP database)',
              required: true,
              default: 'passive',
              options: [
                { label: 'Passive', value: 'passive' },
                { label: 'Active', value: 'active' }
              ]
            }
          ]
        }}
        onOpenChange={() => {}}
        onSubmit={submit}
      />
    </QueryClientProvider>
  )
  expect(screen.getByText('Тайм-аут в миллисекундах. По умолчанию: 1000')).toBeTruthy()
  fireEvent.change(screen.getByRole('textbox', { name: /timeout/ }), { target: { value: '250' } })
  expect(screen.getByRole('combobox', { name: /mode/ }).textContent).toBe('Пассивный')
  fireEvent.keyDown(screen.getByRole('combobox', { name: /mode/ }), { key: 'ArrowDown' })
  fireEvent.click(await screen.findByRole('option', { name: 'Активный' }))
  fireEvent.click(screen.getByRole('button', { name: 'Запустить обогатитель' }))
  await vi.waitFor(() => expect(submit).toHaveBeenCalledTimes(1))
  expect(submit.mock.calls[0][0]).toEqual({ timeout: '250', mode: 'active' })
  client.clear()
})
