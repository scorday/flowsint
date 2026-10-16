# flowsint-app

The folder for the flowsint client, a web application built with Vite and React. The main libraries used are:

- TanstackQuery
- TanstackRouter
- XYflow
- react-force-graph

## Project setup

### Install

```bash
$ npm install
```

### Development

```bash
$ npm run dev
```

This will start the development server at http://localhost:5173

### Build

```bash
$ npm run build
```

This will create a production build in the `dist` folder.

### Preview

```bash
$ npm run start
```

This will start the production build locally.

### Interface languages

The interface supports English (`en`) and Russian (`ru`). The language selector is available in the top navigation, on the sign-in and registration pages, and in AVL4 connection states. The saved `flowsint-language` preference takes priority over supported browser language preferences; otherwise the fallback is English. Changes apply immediately, synchronize across tabs, and update the document language without remounting editors or clearing project state.

Translations live in `src/i18n/locales/en.json` and `ru.json`. Use `useTranslation()` in React components and `translate()` in event handlers or non-React code. English source text is the translation key. Keep validation messages as source keys and translate them in `FormMessage` or the shared `FormField`, so existing errors follow language changes. Translate static option labels when rendering them, leaving option values, API fields, graph data, user content, and URLs unchanged. Include `t` or `dateLocale` in memo dependencies when used inside memoized callbacks. Pass `dateLocale` from the hook to date-fns and `language` to native Intl formatting.

Use `{{name}}` placeholders for dynamic values and `Intl.PluralRules` suffixes (`_one`, `_few`, `_many`, `_other`) with `{ count }` for counts. Unknown keys fall back to English source text. Add keys to both catalogs; `npm test` checks catalog parity, language persistence, tab synchronization, plural rules, and switching without losing form state.

Built-in enricher descriptions, API-key notes, and parameter help are translated in `src/i18n/locales/enrichers.en.json` and `enrichers.ru.json`. These are display-only translations; API names, saved flow data, and submitted parameter values retain their original values. Enricher search matches both the source description and its current translation. After changing built-in metadata, run `uv run --no-project python scripts/check-enricher-locales.py` from `flowsint-app` (requires `uv` and the sibling `flowsint-enrichers` sources); it parses Python with the standard-library AST without importing or executing enrichers and rejects missing, empty, untranslated, or stale entries.
