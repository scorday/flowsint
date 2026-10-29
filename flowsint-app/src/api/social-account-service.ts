import { fetchWithAuth } from './api'

export interface ResolvedSocialAccount extends Record<string, unknown> {
  id: string
  nodeLabel: string
  username: { value: string }
  platform: string
  profile_url: string
  display_name?: string | null
  vk_profile_status: 'open' | 'closed' | 'deactivated' | 'unknown'
}

export const socialAccountService = {
  resolve: (sketchId: string, profileUrl: string): Promise<ResolvedSocialAccount> =>
    fetchWithAuth('/api/types/social-account/resolve', {
      method: 'POST',
      body: JSON.stringify({ sketch_id: sketchId, profile_url: profileUrl })
    })
}
