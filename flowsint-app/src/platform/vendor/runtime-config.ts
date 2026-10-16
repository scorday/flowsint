/** Public frontend configuration. This module has no SDK or framework dependency. */
export interface FrontendSettings {
  readonly apiBaseUrl: string;
  readonly assetBaseUrl: string;
  readonly homeUrl: string;
  readonly loginUrl: string;
  readonly logoutUrl: string;
  readonly adminUrl: string;
  readonly storageBaseUrl: string;
  readonly panelCssUrl: string;
  readonly panelJsUrl: string;
  readonly cookieDomain?: string;
  readonly cardsPrefix: string;
  readonly mode: string;
}

export interface RuntimeConfigLoader {
  get(): FrontendSettings;
  load(): Promise<FrontendSettings>;
}

type LegacyEnvironment = Readonly<Record<string, unknown>>;

export function legacySettings(env: LegacyEnvironment): FrontendSettings {
  const string = (key: string, fallback = "") => typeof env[key] === "string" ? env[key] as string : fallback;
  return Object.freeze({
    apiBaseUrl: string("VITE_BASE_API_URL", "/"),
    assetBaseUrl: string("VITE_BASE_URL", "/"),
    homeUrl: string("VITE_HOME_URL", "/"),
    loginUrl: string("VITE_LOGIN_URL", "/"),
    logoutUrl: string("VITE_LOGOUT_URL", "/"),
    adminUrl: string("VITE_ADMIN_URL", "/"),
    storageBaseUrl: string("VITE_STORAGE_BASE_URL", "/d"),
    panelCssUrl: string("VITE_PANEL_CSS_URL", "/panel/index.css"),
    panelJsUrl: string("VITE_PANEL_JS_URL", "/panel/index.js"),
    cookieDomain: string("VITE_DOMAIN_COOKIE") || undefined,
    cardsPrefix: string("VITE_CARDS_PREFIX", "/web"),
    mode: string("VITE_MODE", "base"),
  });
}

const URL_KEYS = [
  "apiBaseUrl", "assetBaseUrl", "homeUrl", "loginUrl", "logoutUrl", "adminUrl",
  "panelCssUrl", "panelJsUrl", "storageBaseUrl",
] as const;

export function parseRuntimeConfig(value: unknown, application: string): FrontendSettings {
  const invalid = () => new Error("Invalid frontend runtime configuration");
  if (!value || typeof value !== "object") throw invalid();
  const envelope = value as Record<string, unknown>;
  if (envelope.version !== 1 || envelope.application !== application
    || typeof envelope.profile !== "string" || !envelope.profile) throw invalid();
  const domain = envelope.domain;
  if (typeof domain !== "string" || !/^[a-z0-9]+(?:[.-][a-z0-9]+)*$/.test(domain)) throw invalid();
  if (!envelope.settings || typeof envelope.settings !== "object") throw invalid();
  const settings = envelope.settings as Record<string, unknown>;
  for (const key of [...URL_KEYS, "cardsPrefix", "mode"]) {
    if (typeof settings[key] !== "string" || !settings[key] || /[\s\\]/.test(settings[key] as string)) throw invalid();
  }
  for (const key of URL_KEYS) {
    const url = settings[key] as string;
    if (url.startsWith("/") && !url.startsWith("//")) continue;
    let parsed: URL;
    try { parsed = new URL(url); } catch { throw invalid(); }
    if (parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.port
      || (parsed.hostname !== domain && !parsed.hostname.endsWith("." + domain))) throw invalid();
  }
  if (settings.authBypass !== false) throw invalid();
  const cookieDomain = settings.cookieDomain;
  if (typeof cookieDomain !== "string"
    || (cookieDomain !== "" && !/^\.[a-z0-9]+(?:[.-][a-z0-9]+)*$/.test(cookieDomain))) throw invalid();
  if ((cookieDomain && cookieDomain !== "." + domain)
    || (application === "main-panel" && !cookieDomain)) throw invalid();
  if (!/^\/[a-zA-Z0-9_/-]*$/.test(settings.cardsPrefix as string)) throw invalid();
  if (application === "main-panel") {
    const logout = new URL(settings.logoutUrl as string, "https://runtime.invalid");
    const next = logout.searchParams.getAll("next");
    if (next.length !== 1 || /[\s\\]/.test(next[0])) throw invalid();
    let returnUrl: URL;
    try { returnUrl = new URL(next[0]); } catch { throw invalid(); }
    if (returnUrl.protocol !== "https:" || returnUrl.username || returnUrl.password
      || returnUrl.port || (returnUrl.hostname !== domain && !returnUrl.hostname.endsWith("." + domain))) throw invalid();
  }
  // Copy only supported public fields; never publish an unvalidated response object.
  return Object.freeze({
    ...Object.fromEntries(URL_KEYS.map(key => [key, settings[key]])),
    cookieDomain: cookieDomain || undefined,
    cardsPrefix: settings.cardsPrefix,
    mode: settings.mode,
  }) as unknown as FrontendSettings;
}

export function createRuntimeConfig(options: {
  application: string;
  url: URL;
  runtime: boolean;
  legacy?: LegacyEnvironment;
  fetcher?: typeof fetch;
}): RuntimeConfigLoader {
  let settings = options.runtime ? undefined : legacySettings(options.legacy ?? {});
  let pending: Promise<FrontendSettings> | undefined;
  return {
    get() {
      if (!settings) throw new Error("Frontend runtime configuration is not initialized");
      return settings;
    },
    load() {
      if (settings) return Promise.resolve(settings);
      pending ??= (async () => {
        try {
          const response = await (options.fetcher ?? fetch)(options.url, {
            cache: "no-store", credentials: "omit", redirect: "error",
            signal: AbortSignal.timeout(10_000),
          });
          if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) {
            throw new Error();
          }
          settings = parseRuntimeConfig(await response.json(), options.application);
          return settings;
        } catch {
          // Neither server response bodies nor URLs belong in public diagnostics.
          throw new Error("Frontend runtime configuration could not be loaded");
        }
      })();
      return pending;
    },
  };
}

export function mountExternalPanel(settings: FrontendSettings, doc: Document = document): void {
  if (!doc.getElementById("avl4-panel-style")) {
    const style = doc.createElement("link");
    style.id = "avl4-panel-style";
    style.rel = "stylesheet";
    style.href = settings.panelCssUrl;
    doc.head.append(style);
  }
  if (!doc.getElementById("avl4-panel-script")) {
    const script = doc.createElement("script");
    script.id = "avl4-panel-script";
    script.type = "module";
    script.src = settings.panelJsUrl;
    doc.body.append(script);
  }
}

export async function startFrontend(options: {
  loader: RuntimeConfigLoader;
  rootId: string;
  loadApp: () => Promise<unknown>;
  panel?: boolean;
  onFailure?: () => void;
}): Promise<void> {
  try {
    const settings = await options.loader.load();
    // Loading the external module must never delay the public application mount.
    if (options.panel) mountExternalPanel(settings);
    await options.loadApp();
  } catch {
    options.onFailure?.();
    const root = document.getElementById(options.rootId);
    if (root) {
      const message = document.createElement("p");
      message.setAttribute("role", "alert");
      message.textContent = "Не удалось загрузить приложение. Обновите страницу.";
      root.replaceChildren(message);
    }
  }
}
