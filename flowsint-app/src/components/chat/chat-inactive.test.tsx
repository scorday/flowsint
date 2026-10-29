// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { setLanguage } from '@/i18n'
import ChatInactive from './chat-inactive'

vi.mock('@tanstack/react-router', () => ({
  Link: ({ children, to }: { children: ReactNode; to: string }) => <a href={to}>{children}</a>
}))

afterEach(() => {
  cleanup()
  setLanguage('en')
})

it('shows the configured RouterAI key instead of asking for a Mistral key', () => {
  setLanguage('ru')
  render(<ChatInactive keyName="ROUTERAI_API_KEY" onClose={vi.fn()} />)
  expect(screen.getByText('ROUTERAI_API_KEY')).toBeTruthy()
  expect(screen.getByText('Требуется API-ключ')).toBeTruthy()
  expect(screen.queryByText('MISTRAL_API_KEY')).toBeNull()
})

it('uses a neutral label while the configured key name is unavailable', () => {
  setLanguage('en')
  render(<ChatInactive onClose={vi.fn()} />)
  expect(screen.getByText('API key')).toBeTruthy()
  expect(screen.queryByText('MISTRAL_API_KEY')).toBeNull()
})
