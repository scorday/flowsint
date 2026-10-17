// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import en from './locales/types.en.json'
import ru from './locales/types.ru.json'
import { setLanguage, translateFor } from './index'
import AddItemDialog from '@/components/sketches/add-item-dialog'
import { useGraphStore } from '@/stores/graph-store'
import type { ActionItem } from '@/lib/action-items'

vi.hoisted(() => {
  const values = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key)
  })
})

const fixtures = vi.hoisted(() => ({ items: [] as ActionItem[] }))
vi.mock('@/hooks/use-action-items', () => ({
  useActionItems: () => ({ actionItems: fixtures.items, isLoading: false })
}))
vi.mock('@/hooks/use-icon', () => ({ useIcon: () => () => null }))
vi.mock('@tanstack/react-router', () => ({ useParams: () => ({ id: 'sketch-id' }) }))
vi.mock('@/api/sketch-service', () => ({ sketchService: {} }))

const makeType = (type: string, description: string, count: number): ActionItem => ({
  id: count,
  type,
  key: type.toLowerCase(),
  icon: type.toLowerCase(),
  label: type,
  label_key: 'value',
  description,
  fields: Array.from({ length: count }, (_, index) => ({
    name: index === 0 ? 'value' : `field_${index}`,
    label: index === 0 ? 'Value' : `Field ${index}`,
    type: 'text',
    required: false
  }))
})

beforeEach(() => {
  setLanguage('ru')
  fixtures.items = [
    makeType('Phrase', 'Represents a phrase or text content.', 1),
    makeType('Location', 'Represents a physical address with geographical coordinates.', 6),
    makeType(
      'Individual',
      'Represents an individual person with comprehensive personal information.',
      82
    ),
    makeType('Username', 'Represents a username or handle on any platform.', 3),
    makeType('Research subject', 'User-authored description', 2)
  ]
  useGraphStore.setState({
    openMainDialog: true,
    openFormDialog: false,
    currentNodeType: null,
    relatedNodeToAdd: null
  })
})

afterEach(() => {
  cleanup()
  setLanguage('en')
  useGraphStore.setState({ openMainDialog: false, openFormDialog: false, currentNodeType: null })
})

it('provides matching catalogs with translated metadata and exact English fallback', () => {
  expect(Object.keys(en).sort()).toEqual(Object.keys(ru).sort())
  for (const [source, translated] of Object.entries(ru)) {
    expect(translateFor('en', source)).toBe(source)
    expect(translateFor('ru', source)).toBe(translated)
    expect(translated.trim()).not.toBe('')
    expect(translated).not.toBe(source)
  }
})

it('translates API type cards and field counts and switches languages in place', () => {
  render(<AddItemDialog />)
  expect(screen.getByText('Фраза')).toBeTruthy()
  expect(screen.getByText('Фраза или текстовое содержимое.')).toBeTruthy()
  expect(screen.getByText('Местоположение')).toBeTruthy()
  expect(screen.getByText('Человек')).toBeTruthy()
  expect(screen.getByText('Имя пользователя')).toBeTruthy()
  for (const count of ['1 поле', '2 поля', '3 поля', '6 полей', '82 поля']) {
    expect(screen.getByText(count)).toBeTruthy()
  }
  expect(screen.getByText('Research subject')).toBeTruthy()
  expect(screen.getByText('User-authored description')).toBeTruthy()
  act(() => setLanguage('en'))
  expect(screen.getByText('Phrase')).toBeTruthy()
  expect(screen.getByText('Represents a phrase or text content.')).toBeTruthy()
  expect(screen.getByText('1 field')).toBeTruthy()
  expect(screen.getByText('82 fields')).toBeTruthy()
  act(() => setLanguage('ru'))
  expect(screen.getByText('Фраза')).toBeTruthy()
})

it.each(['фраза', 'текстовое', 'PHRASE'])(
  'searches translated names/descriptions and original identifiers for %s',
  async (query) => {
    render(<AddItemDialog />)
    fireEvent.change(screen.getByPlaceholderText('Поиск типов…'), { target: { value: query } })
    await waitFor(() => expect(screen.queryByText('Местоположение')).toBeNull())
    expect(screen.getByText('Фраза')).toBeTruthy()
  }
)

it('recomputes translated search results on language change without clearing the query', async () => {
  render(<AddItemDialog />)
  fireEvent.change(screen.getByPlaceholderText('Поиск типов…'), { target: { value: 'фраза' } })
  await waitFor(() => expect(screen.queryByText('Местоположение')).toBeNull())
  act(() => setLanguage('en'))
  expect(await screen.findByText('No types match "фраза"')).toBeTruthy()
  expect((screen.getByPlaceholderText('Search types...') as HTMLInputElement).value).toBe('фраза')
  act(() => setLanguage('ru'))
  expect(await screen.findByText('Фраза')).toBeTruthy()
})

it('opens the translated creation form with the original type and preserves entered data', async () => {
  render(<AddItemDialog />)
  fireEvent.click(screen.getByText('Фраза'))
  expect(await screen.findByRole('heading', { name: 'Добавить сущность: Фраза' })).toBeTruthy()
  expect(screen.getByText('Фраза или текстовое содержимое.')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Добавить сущность: Фраза' })).toBeTruthy()
  expect(useGraphStore.getState().currentNodeType).toBe(fixtures.items[0])
  expect(useGraphStore.getState().currentNodeType?.type).toBe('Phrase')
  fireEvent.change(screen.getByLabelText('Value'), { target: { value: 'User data' } })
  act(() => setLanguage('en'))
  expect(screen.getByRole('heading', { name: 'Add entity: Phrase' })).toBeTruthy()
  expect((screen.getByLabelText('Value') as HTMLInputElement).value).toBe('User data')
  expect(fixtures.items[0].description).toBe('Represents a phrase or text content.')
})
