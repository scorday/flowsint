// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { setLanguage } from '@/i18n'
import { SocialAccountForm } from './social-account-form'
import type { ActionItem } from '@/lib/action-items'

vi.hoisted(() => {
  vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => undefined })
})
const api = vi.hoisted(() => ({ resolve: vi.fn() }))
vi.mock('@/api/social-account-service', () => ({ socialAccountService: api }))

const type: ActionItem = {
  id: 1,
  type: 'SocialAccount',
  key: 'socialaccount',
  label: 'SocialAccount',
  label_key: 'username',
  icon: 'socialaccount',
  description: '',
  fields: [{ name: 'username', label: 'Username', type: 'text', required: false }]
}
const profile = {
  id: 'id515596@vk.ru',
  nodeLabel: 'id515596@vk.ru',
  username: { value: 'id515596' },
  platform: 'vk.ru',
  profile_url: 'https://vk.ru/id515596',
  display_name: 'Test Person',
  vk_profile_status: 'open'
}

beforeEach(() => {
  setLanguage('ru')
  api.resolve.mockReset().mockResolvedValue(profile)
})
afterEach(() => {
  cleanup()
  setLanguage('en')
})

async function resolveLink() {
  fireEvent.change(screen.getByLabelText('Ссылка на профиль'), {
    target: { value: 'https://vk.com/alias' }
  })
  fireEvent.click(screen.getByRole('button', { name: 'Получить профиль' }))
  await screen.findByText('Test Person')
}

it('previews a VK link and submits the canonical social account with explicit friend opt-in', async () => {
  const submit = vi.fn().mockResolvedValue(undefined)
  render(<SocialAccountForm currentNodeType={type} sketchId="sketch" onSubmit={submit} />)
  await resolveLink()
  expect(api.resolve).toHaveBeenCalledWith('sketch', 'https://vk.com/alias')
  expect(screen.getByText('VK · Открытый профиль')).toBeTruthy()
  expect(submit).not.toHaveBeenCalled()
  const friends = screen.getByRole('checkbox') as HTMLInputElement
  expect(friends.checked).toBe(false)
  fireEvent.click(friends)
  fireEvent.click(screen.getByRole('button', { name: 'Добавить профиль' }))
  await waitFor(() => expect(submit).toHaveBeenCalledWith(profile, true))
})

it.each(['closed', 'unknown', 'deactivated'])(
  'does not offer friend loading for %s profiles',
  async (status) => {
    api.resolve.mockResolvedValue({ ...profile, vk_profile_status: status })
    const submit = vi.fn().mockResolvedValue(undefined)
    render(<SocialAccountForm currentNodeType={type} sketchId="sketch" onSubmit={submit} />)
    await resolveLink()
    expect(screen.queryByRole('checkbox')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Добавить профиль' }))
    await waitFor(() =>
      expect(submit).toHaveBeenCalledWith({ ...profile, vk_profile_status: status }, false)
    )
  }
)

it('preserves the URL after provider failure and allows retry', async () => {
  api.resolve.mockRejectedValueOnce(new Error('provider failure'))
  render(<SocialAccountForm currentNodeType={type} sketchId="sketch" onSubmit={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('Ссылка на профиль'), {
    target: { value: 'https://vk.com/alias' }
  })
  fireEvent.click(screen.getByRole('button', { name: 'Получить профиль' }))
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect((screen.getByLabelText('Ссылка на профиль') as HTMLInputElement).value).toBe(
    'https://vk.com/alias'
  )
  fireEvent.click(screen.getByRole('button', { name: 'Получить профиль' }))
  expect(await screen.findByText('Test Person')).toBeTruthy()
})

it('keeps manual entry available without requesting VK', async () => {
  const submit = vi.fn().mockResolvedValue(undefined)
  render(<SocialAccountForm currentNodeType={type} sketchId="sketch" onSubmit={submit} />)
  fireEvent.click(screen.getByRole('button', { name: 'Ввести вручную' }))
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'other_user' } })
  fireEvent.click(screen.getByRole('button', { name: 'Добавить сущность: Аккаунт в соцсети' }))
  await waitFor(() => expect(submit).toHaveBeenCalledWith({ username: 'other_user' }))
  expect(api.resolve).not.toHaveBeenCalled()
})
