import { type Sketch } from './sketch'
import { type Profile } from './profile'
import { type Analysis } from './analysis'

export type InvestigationRole = 'owner' | 'admin' | 'editor' | 'viewer'

export interface Investigation {
  id: string
  name: string
  description: string
  sketches: Sketch[]
  analyses: Analysis[]
  created_at: string
  last_updated_at: string
  owner: Profile | null
  owner_id: string | null
  project_id?: string
  created_by?: string | null
  status: string
  current_user_role: InvestigationRole | null
}

export interface Collaborator {
  id: string
  user_id: string
  roles: string[]
  user: Profile | null
}
