// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import Login from './login'
import { setLanguage } from '@/i18n'

vi.mock('@/hooks/use-auth', () => ({
  useLogin: () => ({ mutateAsync: vi.fn(), isPending: false, error: null })
}))
vi.mock('@tanstack/react-router', () => ({
  createFileRoute: () => (options: unknown) => options,
  redirect: vi.fn(),
  Link: ({ children, to }: { children: ReactNode; to: string }) => <a href={to}>{children}</a>
}))

beforeEach(() => setLanguage('en'))
afterEach(cleanup)

it('translates visible validation errors when switching language and keeps typed input', async () => {
  render(<Login />)
  fireEvent.click(screen.getByRole('button', { name: 'Sign In' }))
  await screen.findByText('Password is required')
  fireEvent.change(screen.getByRole('textbox', { name: 'Email' }), {
    target: { value: 'analyst@example.invalid' }
  })
  fireEvent.change(screen.getByRole('combobox', { name: 'Language' }), {
    target: { value: 'ru' }
  })
  expect(screen.getByText('Укажите пароль')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Войти' })).toBeTruthy()
  expect(
    (screen.getByRole('textbox', { name: 'Электронная почта' }) as HTMLInputElement).value
  ).toBe('analyst@example.invalid')
  fireEvent.change(screen.getByRole('combobox', { name: 'Язык' }), {
    target: { value: 'en' }
  })
  expect(screen.getByText('Password is required')).toBeTruthy()
})
