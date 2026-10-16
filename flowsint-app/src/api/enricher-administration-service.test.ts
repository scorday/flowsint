import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchWithAuth } from './api'
import {
  enricherAdministrationService,
  type AdminEnricher
} from './enricher-administration-service'

vi.mock('./api', () => ({ fetchWithAuth: vi.fn() }))
beforeEach(() => vi.clearAllMocks())
describe('enricher administration API', () => {
  it('encodes the enricher identifier and sends the requested visibility', async () => {
    const enricher: AdminEnricher = {
      id: 'some/name with spaces',
      kind: 'builtin',
      name: 'Example',
      category: 'test',
      description: null,
      input_type: 'domain',
      output_type: 'ip',
      is_visible: true
    }
    const updated = { ...enricher, is_visible: false }
    vi.mocked(fetchWithAuth).mockResolvedValue(updated)
    expect(await enricherAdministrationService.setVisibility(enricher, false)).toEqual(updated)
    expect(fetchWithAuth).toHaveBeenCalledWith(
      '/api/enrichers/administration/builtin/some%2Fname%20with%20spaces',
      { method: 'PATCH', body: JSON.stringify({ is_visible: false }) }
    )
  })
})
