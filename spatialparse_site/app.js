const API_BASE = resolveApiBase();
const WS_URL = apiBaseToWs(API_BASE) + '/ws/parse';

const COLORS = ['#0d5eaf', '#0c8177', '#bb762f', '#67549d', '#257451', '#b92d36'];
const FINAL_COLOR = '#bb762f';
const REF_COLOR = '#6f7a83';

const state = {
  token: localStorage.getItem('spatialparse_token') || '',
  user: readCachedUser(),
  summary: null,
  map: null,
  accountMap: null,
  layers: [],
  accountLayers: [],
  lastRun: null,
  isRunning: false,
  runStatus: 'idle',
  activeWebSocket: null,
  runTimeoutId: null,
  authReturnFocus: null,
  saveDialogResolve: null,
  saveReturnFocus: null,
  confirmDialogResolve: null,
  confirmReturnFocus: null,
  accountAbortController: null,
  history: [],
  saved: []
};

const $ = (id) => document.getElementById(id);
const RECENT_QUERY_KEY = 'spatialparse_recent_queries';
const COOKIE_CONSENT_KEY = 'spatialparse_cookie_consent_v1';
const ACCOUNT_PREFS_KEY = 'spatialparse_account_preferences';
const CONSENT_DOCUMENT_VERSION = '2026-08-03';
const DEMO_RUN_TIMEOUT_MS = 90000;

const els = {
  scrollProgress: $('scrollProgress'),
  queryInput: $('queryInput'),
  queryCounter: $('queryCounter'),
  runBtn: $('runBtn'),
  saveResultBtn: $('saveResultBtn'),
  clearQueryBtn: $('clearQueryBtn'),
  clearBtn: $('clearBtn'),
  recentQueries: $('recentQueries'),
  statusPill: $('statusPill'),
  statusText: $('statusText'),
  stepsList: $('stepsList'),
  mapSubtitle: $('mapSubtitle'),
  authOpenBtn: $('authOpenBtn'),
  logoutBtn: $('logoutBtn'),
  userChip: $('userChip'),
  openAccountBtn: $('openAccountBtn'),
  authModal: $('authModal'),
  loginTab: $('loginTab'),
  registerTab: $('registerTab'),
  loginForm: $('loginForm'),
  registerForm: $('registerForm'),
  authMessage: $('authMessage'),
  accountGuest: $('accountGuest'),
  accountDashboard: $('accountDashboard'),
  historyCount: $('historyCount'),
  savedCount: $('savedCount'),
  lastActivity: $('lastActivity'),
  historyList: $('historyList'),
  savedList: $('savedList'),
  refreshHistoryBtn: $('refreshHistoryBtn'),
  refreshSavedBtn: $('refreshSavedBtn'),
  saveSettingsBtn: $('saveSettingsBtn'),
  toast: $('toast')
};

document.addEventListener('DOMContentLoaded', init);

function init() {
  initTheme();
  initPageTransitions();
  initIcons();
  initSeoMetadata();
  initNavigation();
  initCookieConsent();
  initFooterSupport();
  initShellAnimations();
  initA11y();
  initVisualMaps();
  initWorkbench();
  initAccountMap();
  bindAuth();
  bindDemoLinks();
  bindPlannedActions();
  renderAuthState();
  applyQueryParam();
  applyAuthParam();
  loadAccount({ silent: true });
}

function resolveApiBase() {
  const { protocol, origin } = window.location;
  if (protocol === 'file:') return 'http://localhost:8000';
  return origin;
}

function apiBaseToWs(apiBase) {
  const url = new URL(apiBase);
  return (url.protocol === 'https:' ? 'wss://' : 'ws://') + url.host;
}

const THEME_KEY = 'sp_theme';

function initTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  const preferred = saved || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const actions = document.querySelector('.auth-actions');
  if (actions && !document.getElementById('themeToggle')) {
    const button = document.createElement('button');
    button.id = 'themeToggle';
    button.type = 'button';
    button.className = 'icon-btn';
    button.title = 'Сменить тему';
    button.setAttribute('aria-label', 'Сменить тему');
    actions.prepend(button);
    button.addEventListener('click', () => {
      const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      applyTheme(next);
      localStorage.setItem(THEME_KEY, next);
    });
  }
  applyTheme(preferred);
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const button = document.getElementById('themeToggle');
  if (button) {
    button.innerHTML = `<i data-lucide="${theme === 'dark' ? 'sun' : 'moon'}"></i>`;
    initIcons();
  }
}

function initPageTransitions() {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  document.body.classList.add('page-enter');
  document.addEventListener('click', (event) => {
    const link = event.target.closest('a[href]');
    if (!link || link.target === '_blank' || link.hasAttribute('download')) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
    let url;
    try {
      url = new URL(link.href, window.location.href);
    } catch (error) {
      return;
    }
    if (url.origin !== window.location.origin) return;
    if (url.pathname === window.location.pathname) return;
    event.preventDefault();
    document.body.classList.add('page-leave');
    window.setTimeout(() => { window.location.href = url.href; }, 190);
  });
  window.addEventListener('pageshow', (event) => {
    if (event.persisted) document.body.classList.remove('page-leave');
  });
}

function initIcons() {
  if (window.lucide) window.lucide.createIcons();
}

function initSeoMetadata() {
  const description = document.querySelector('meta[name="description"]')?.content || '';
  const title = document.title || 'SpatialParse';
  const url = window.location.href.split('#')[0];

  ensureLink('canonical', url);
  const icon = ensureLink('icon', '/site/favicon.svg');
  if (icon) icon.type = 'image/svg+xml';
  ensureLink('manifest', '/site.webmanifest');
  ensureMeta('name', 'theme-color', '#0d5eaf');
  ensureMeta('property', 'og:type', 'website');
  ensureMeta('property', 'og:site_name', 'SpatialParse');
  ensureMeta('property', 'og:title', title);
  ensureMeta('property', 'og:description', description);
  ensureMeta('property', 'og:url', url);
  ensureMeta('name', 'twitter:card', 'summary_large_image');
  ensureMeta('name', 'twitter:title', title);
  ensureMeta('name', 'twitter:description', description);
}

function ensureMeta(attribute, key, content) {
  if (!content) return;
  let meta = document.querySelector(`meta[${attribute}="${key}"]`);
  if (!meta) {
    meta = document.createElement('meta');
    meta.setAttribute(attribute, key);
    document.head.appendChild(meta);
  }
  meta.setAttribute('content', content);
}

function ensureLink(rel, href) {
  if (!href) return;
  let link = document.querySelector(`link[rel="${rel}"]`);
  if (!link) {
    link = document.createElement('link');
    link.rel = rel;
    document.head.appendChild(link);
  }
  link.href = href;
  return link;
}

function initNavigation() {
  const page = document.body.dataset.page || 'home';
  const links = [
    ['home', 'Главная', 'index.html'],
    ['features', 'Возможности', 'features.html'],
    ['demo', 'Демо', 'demo.html'],
    ['docs', 'Документация', 'docs.html'],
    ['pricing', 'Тарифы', 'pricing.html'],
    ['about', 'О проекте', 'about.html'],
    ['account', 'Кабинет', 'account.html']
  ];

  document.querySelectorAll('.nav-links').forEach((nav) => {
    nav.innerHTML = links.map(([key, label, href]) => (
      `<a class="${page === key ? 'active' : ''}" href="${href}">${label}</a>`
    )).join('');
  });

  document.querySelectorAll('.footer-links').forEach((nav) => {
    if (nav.querySelector('[href="privacy.html#cookies"]')) return;
    const link = document.createElement('a');
    link.href = 'privacy.html#cookies';
    link.textContent = 'Cookie';
    nav.appendChild(link);
  });

  const setMobileMenuButton = (button, opened) => {
    if (!button) return;
    button.setAttribute('aria-expanded', String(opened));
    button.setAttribute('aria-label', opened ? 'Закрыть меню' : 'Открыть меню');
    button.innerHTML = opened ? '<i data-lucide="x"></i>' : '<i data-lucide="menu"></i>';
    initIcons();
  };

  const closeMobileNav = (topbar, options = {}) => {
    const button = topbar.querySelector('.mobile-menu-btn');
    topbar.classList.remove('nav-open');
    setMobileMenuButton(button, false);
    if (options.restoreFocus) {
      button?.focus();
    }
  };

  document.querySelectorAll('.topbar').forEach((topbar) => {
    let button = topbar.querySelector('.mobile-menu-btn');
    if (!button) {
      button = document.createElement('button');
      button.className = 'icon-btn mobile-menu-btn';
      button.type = 'button';
      button.id = 'mobileMenuBtn';
      button.setAttribute('aria-label', 'Открыть меню');
      button.setAttribute('aria-expanded', 'false');
      button.innerHTML = '<i data-lucide="menu"></i>';
      topbar.querySelector('.brand')?.insertAdjacentElement('afterend', button);
    }

    button.addEventListener('click', (event) => {
      event.stopPropagation();
      const opened = topbar.classList.toggle('nav-open');
      setMobileMenuButton(button, opened);
      if (opened) {
        window.setTimeout(() => topbar.querySelector('.nav-links a')?.focus(), 30);
      }
    });

    topbar.querySelectorAll('.nav-links a').forEach((link) => {
      link.addEventListener('click', () => {
        closeMobileNav(topbar);
      });
    });
  });

  document.addEventListener('click', (event) => {
    document.querySelectorAll('.topbar.nav-open').forEach((topbar) => {
      if (topbar.contains(event.target)) return;
      closeMobileNav(topbar);
    });
  });

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    document.querySelectorAll('.topbar.nav-open').forEach((topbar) => {
      closeMobileNav(topbar, { restoreFocus: true });
    });
  });

  initIcons();
}

function enhanceAuthModal() {
  const modal = els.authModal;
  if (!modal || modal.dataset.authUiReady) return;
  modal.dataset.authUiReady = 'true';

  if (els.registerForm && !els.registerForm.querySelector('input[name="password_repeat"]')) {
    const passwordLabel = els.registerForm.querySelector('input[name="password"]')?.closest('label');
    if (passwordLabel) {
      const repeatLabel = document.createElement('label');
      repeatLabel.innerHTML = '<span>Повторите пароль</span><input name="password_repeat" type="password" autocomplete="new-password" minlength="8" required>';
      passwordLabel.after(repeatLabel);
    }
  }

  const decorate = (form, fields) => {
    if (!form) return;
    fields.forEach(({ name, placeholder, icon }) => {
      const input = form.querySelector(`input[name="${name}"]`);
      if (!input || input.closest('.input-wrap')) return;
      input.placeholder = placeholder;
      const wrap = document.createElement('span');
      wrap.className = 'input-wrap';
      input.parentNode.insertBefore(wrap, input);
      wrap.appendChild(input);
      if (icon === 'eye') {
        const toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.className = 'password-toggle';
        toggle.setAttribute('aria-label', 'Показать пароль');
        toggle.innerHTML = '<i data-lucide="eye"></i>';
        toggle.addEventListener('click', () => {
          const show = input.type === 'password';
          input.type = show ? 'text' : 'password';
          toggle.setAttribute('aria-label', show ? 'Скрыть пароль' : 'Показать пароль');
          toggle.innerHTML = `<i data-lucide="${show ? 'eye-off' : 'eye'}"></i>`;
          initIcons();
          input.focus();
        });
        wrap.appendChild(toggle);
      } else if (icon) {
        const badge = document.createElement('span');
        badge.className = 'input-icon';
        badge.innerHTML = `<i data-lucide="${icon}"></i>`;
        wrap.appendChild(badge);
      }
    });
  };

  decorate(els.loginForm, [
    { name: 'email', placeholder: 'Введите ваш email', icon: 'mail' },
    { name: 'password', placeholder: 'Введите ваш пароль', icon: 'eye' }
  ]);
  decorate(els.registerForm, [
    { name: 'name', placeholder: 'Введите ваше имя', icon: 'user' },
    { name: 'email', placeholder: 'Введите ваш email', icon: 'mail' },
    { name: 'password', placeholder: 'Создайте пароль', icon: 'eye' },
    { name: 'password_repeat', placeholder: 'Повторите пароль', icon: 'eye' }
  ]);

  const loginSubmit = els.loginForm?.querySelector('button[type="submit"]');
  if (loginSubmit && !els.loginForm.querySelector('.auth-aux-row')) {
    const row = document.createElement('div');
    row.className = 'auth-aux-row';
    row.innerHTML = `
      <label class="remember-me"><input type="checkbox" name="remember" checked><span>Запомнить меня</span></label>
      <button type="button" class="forgot-link">Забыли пароль?</button>`;
    loginSubmit.before(row);
    row.querySelector('.forgot-link').addEventListener('click', () => setAuthMode('reset'));
  }

  if (els.loginForm && !modal.querySelector('#resetForm')) {
    const resetForm = document.createElement('form');
    resetForm.id = 'resetForm';
    resetForm.className = 'auth-form';
    resetForm.hidden = true;
    resetForm.innerHTML = `
      <p class="auth-reset-sub">Укажите email аккаунта — мы пришлём инструкцию по восстановлению пароля.</p>
      <label><span>Email</span><span class="input-wrap"><input name="email" type="email" autocomplete="email" placeholder="Введите ваш email" required><span class="input-icon"><i data-lucide="mail"></i></span></span></label>
      <button class="btn primary full" type="submit"><i data-lucide="send"></i><span>Отправить инструкцию</span></button>
      <button class="forgot-link auth-back-link" type="button">← Вернуться ко входу</button>`;
    els.loginForm.after(resetForm);
    resetForm.querySelector('.auth-back-link').addEventListener('click', () => setAuthMode('login'));
    resetForm.addEventListener('submit', (event) => {
      event.preventDefault();
      setAuthMessage('');
      const note = document.createElement('p');
      note.className = 'auth-reset-done';
      note.innerHTML = '<i data-lucide="mail-check"></i><span>Заявка принята. Автоматическая отправка писем скоро заработает — а пока напишите нам, и мы восстановим доступ вручную.</span>';
      const existing = resetForm.querySelector('.auth-reset-done');
      if (existing) existing.remove();
      resetForm.querySelector('button[type="submit"]').after(note);
      initIcons();
    });
  }

  if (els.loginForm && !els.loginForm.querySelector('.auth-legal-note')) {
    const note = document.createElement('p');
    note.className = 'auth-legal-note';
    note.innerHTML = 'Входя в систему, вы соглашаетесь с нашими <a href="terms.html">условиями использования</a> и <a href="privacy.html">политикой конфиденциальности</a>.';
    els.loginForm.appendChild(note);
  }

  initIcons();
}

function enhanceAuthConsent() {
  document.querySelectorAll('.auth-consent').forEach((label) => {
    const checkbox = label.querySelector('input[type="checkbox"]');
    const textNode = label.querySelector('span');
    if (checkbox && !label.dataset.consentReady) {
      label.dataset.consentReady = 'true';
      label.addEventListener('click', (event) => {
        if (event.target === checkbox || event.target.closest('a')) return;
        event.preventDefault();
        checkbox.checked = !checkbox.checked;
        checkbox.dispatchEvent(new Event('input', { bubbles: true }));
        checkbox.dispatchEvent(new Event('change', { bubbles: true }));
      });
    }
    if (textNode && !textNode.querySelector('a')) {
      textNode.innerHTML = `
        Я принимаю
        <a href="terms.html">пользовательское соглашение</a>,
        <a href="consent.html">согласие на обработку персональных данных</a>
        и подтверждаю ознакомление с
        <a href="privacy.html#data">политикой обработки данных</a>.
      `;
    }
    label.querySelectorAll('a').forEach((link) => {
      if (link.dataset.consentLinkReady) return;
      link.dataset.consentLinkReady = 'true';
      link.addEventListener('click', (event) => event.stopPropagation());
    });
  });

  document.querySelectorAll('#registerForm .btn.primary').forEach((button) => {
    button.classList.add('register-submit');
  });
}

function initCookieConsent() {
  document.querySelectorAll('[data-open-cookie-settings]').forEach((button) => {
    button.addEventListener('click', () => showCookieBanner({ force: true }));
  });

  const saved = getCookieConsent();
  if (saved && saved.choice) return;
  window.setTimeout(() => showCookieBanner(), 600);
}

function getCookieConsent() {
  try {
    return JSON.parse(localStorage.getItem(COOKIE_CONSENT_KEY) || 'null');
  } catch (error) {
    return null;
  }
}

function canStorePreferences() {
  return Boolean(getCookieConsent()?.categories?.preferences);
}

function saveCookieConsent(choice, categories = {}) {
  const preferences = Boolean(categories.preferences);
  const payload = {
    choice,
    version: '2026-08-03',
    updated_at: new Date().toISOString(),
    categories: {
      necessary: true,
      preferences,
      analytics: false,
      marketing: false
    }
  };
  localStorage.setItem(COOKIE_CONSENT_KEY, JSON.stringify(payload));
  if (!preferences) {
    localStorage.removeItem(RECENT_QUERY_KEY);
    renderRecentQueries();
  }
  hideCookieBanner();
  showToast(preferences ? 'Настройки хранения сохранены' : 'Сохранен режим только необходимых cookie');
}

function showCookieBanner(options = {}) {
  let banner = $('cookieBanner');
  if (!banner) {
    banner = document.createElement('section');
    banner.id = 'cookieBanner';
    banner.className = 'cookie-banner';
    banner.setAttribute('aria-label', 'Согласие на использование cookie');
    banner.setAttribute('aria-live', 'polite');
    banner.innerHTML = `
      <div class="cookie-copy">
        <strong>Cookie и хранение данных</strong>
        <p>Используем только нужные cookie и localStorage для входа, истории демо-запросов, согласия и работы карты. Аналитика и реклама отключены; запросы к карте, геокодеру, маршрутам и LLM могут уходить во внешние сервисы.</p>
        <a href="privacy.html#cookies">Политика конфиденциальности</a>
      </div>
      <div class="cookie-controls">
        <button class="btn secondary small cookie-settings-toggle" type="button" aria-expanded="false" aria-controls="cookieSettingsPanel" data-cookie-settings-toggle>
          <i data-lucide="settings-2" aria-hidden="true"></i>
          <span>Настройки</span>
          <i class="cookie-chevron" data-lucide="chevron-down" aria-hidden="true"></i>
        </button>
        <div class="cookie-actions">
          <button class="btn primary small" type="button" data-cookie-accept><i data-lucide="check" aria-hidden="true"></i>Принять</button>
          <button class="btn secondary small" type="button" data-cookie-essential><i data-lucide="shield-check" aria-hidden="true"></i>Только необходимые</button>
        </div>
      </div>
      <div class="cookie-settings-panel" id="cookieSettingsPanel" hidden>
        <label class="cookie-category active">
          <input type="checkbox" checked disabled>
          <span>Необходимые</span>
          <em>Всегда включены: вход, согласие и базовая работа интерфейса.</em>
        </label>
        <label class="cookie-category">
          <input type="checkbox" data-cookie-preferences>
          <span>Предпочтения</span>
          <em>Последние демо-запросы и удобство повторной работы.</em>
        </label>
        <label class="cookie-category disabled">
          <input type="checkbox" disabled>
          <span>Аналитика и маркетинг</span>
          <em>Не используются в текущей версии сайта.</em>
        </label>
        <button class="btn secondary small cookie-save-choice" type="button" data-cookie-save-choice>Сохранить выбор</button>
      </div>
    `;
    document.body.appendChild(banner);
    initIcons();
  }

  banner.hidden = false;
  const preferenceToggle = banner.querySelector('[data-cookie-preferences]');
  if (preferenceToggle) {
    preferenceToggle.checked = Boolean(getCookieConsent()?.categories?.preferences);
  }
  bindCookieBanner(banner);

  if (options.force) {
    setCookieSettingsOpen(banner, true);
    banner.scrollIntoView({ behavior: 'auto', block: 'end' });
  }
}

function bindCookieBanner(banner) {
  if (banner.dataset.cookieReady) return;
  banner.dataset.cookieReady = 'true';

  banner.querySelector('[data-cookie-settings-toggle]')?.addEventListener('click', () => {
    const opened = banner.classList.contains('settings-open');
    setCookieSettingsOpen(banner, !opened);
  });
  banner.querySelector('[data-cookie-accept]')?.addEventListener('click', () => saveCookieConsent('accepted', { preferences: true }));
  banner.querySelector('[data-cookie-essential]')?.addEventListener('click', () => saveCookieConsent('essential', { preferences: false }));
  banner.querySelector('[data-cookie-save-choice]')?.addEventListener('click', () => {
    const preferences = Boolean(banner.querySelector('[data-cookie-preferences]')?.checked);
    saveCookieConsent(preferences ? 'custom' : 'essential', { preferences });
  });
}

function setCookieSettingsOpen(banner, open) {
  const panel = banner.querySelector('#cookieSettingsPanel');
  const toggle = banner.querySelector('[data-cookie-settings-toggle]');
  if (!panel || !toggle) return;

  banner.classList.toggle('settings-open', open);
  panel.hidden = !open;
  toggle.setAttribute('aria-expanded', String(open));
}

function hideCookieBanner() {
  const banner = $('cookieBanner');
  if (banner) banner.hidden = true;
}

function initFooterSupport() {
  const footer = document.querySelector('footer.footer');
  if (!footer || footer.querySelector('.footer-support')) return;
  const block = document.createElement('div');
  block.className = 'container footer-support';
  block.innerHTML = `
    <div class="footer-support-logos">
      <img src="assets/logo-fasie.png" alt="Фонд содействия инновациям" loading="lazy">
      <img src="assets/logo-putp.png" alt="Платформа университетского технологического предпринимательства" loading="lazy">
    </div>
    <p>Проект реализован при поддержке Фонда содействия инновациям в рамках программы «Студенческий стартап» мероприятия «Платформа университетского технологического предпринимательства» федерального проекта «Технологии».</p>
  `;
  footer.prepend(block);
}

function initA11y() {
  if (els.toast) {
    els.toast.setAttribute('role', 'status');
    els.toast.setAttribute('aria-live', 'polite');
    els.toast.setAttribute('aria-atomic', 'true');
  }

  document.querySelectorAll('.result-tabs').forEach((tabs) => {
    tabs.setAttribute('role', 'tablist');
    tabs.setAttribute('aria-label', 'Разделы результата');
  });

  document.querySelectorAll('.result-tabs button').forEach((button, index) => {
    const tabName = ['result', 'steps', 'source', 'warnings'][index] || String(index);
    button.dataset.resultTab = tabName;
    button.id = button.id || 'resultTab-' + tabName;
    button.setAttribute('role', 'tab');
    button.setAttribute('aria-controls', 'resultPanel-' + tabName);
    button.setAttribute('aria-selected', button.classList.contains('active') ? 'true' : 'false');
    button.tabIndex = button.classList.contains('active') ? 0 : -1;
  });
}

function bindPlannedActions() {
  $('historySearch')?.addEventListener('input', renderHistory);
  document.querySelector('#history .account-tools select')?.addEventListener('change', renderHistory);
  els.saveSettingsBtn?.addEventListener('click', saveAccountSettings);
  initAccountPreferences();
  disableUnavailableCollectionFilters();

  document.querySelectorAll('[data-data-action]').forEach((button) => {
    button.addEventListener('click', async () => {
      const action = button.dataset.dataAction;
      if (action === 'export-account') await exportAccountData();
      if (action === 'clear-history') await clearAccountHistory();
      if (action === 'delete-account') await deleteAccount();
    });
  });

  document.querySelectorAll('.result-tabs button').forEach((button) => {
    button.addEventListener('click', () => {
      setResultTab(button.dataset.resultTab || 'result');
    });

    button.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      const tabs = Array.from(button.closest('.result-tabs')?.querySelectorAll('button') || []);
      if (!tabs.length) return;
      event.preventDefault();
      const current = tabs.indexOf(button);
      const next = event.key === 'Home'
        ? 0
        : event.key === 'End'
          ? tabs.length - 1
          : (current + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      tabs[next].focus();
      tabs[next].click();
    });
  });
}

function getAccountPreferences() {
  try {
    const parsed = JSON.parse(localStorage.getItem(ACCOUNT_PREFS_KEY) || '{}');
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch (error) {
    return {};
  }
}

function initAccountPreferences() {
  const prefs = getAccountPreferences();
  if ($('defaultRegion') && prefs.defaultRegion) $('defaultRegion').value = prefs.defaultRegion;
  if ($('defaultRadius') && prefs.defaultRadius) $('defaultRadius').value = prefs.defaultRadius;
  if ($('defaultMode') && prefs.defaultMode) $('defaultMode').value = prefs.defaultMode;
  if ($('mapStyle') && prefs.mapStyle) $('mapStyle').value = prefs.mapStyle;
}

function disableUnavailableCollectionFilters() {
  document.querySelectorAll('.collection-strip button:not(.active)').forEach((button) => {
    button.disabled = true;
    button.title = 'Коллекции появятся после добавления тегов к сохраненным результатам';
    button.setAttribute('aria-disabled', 'true');
  });
}

function updateResultTabState(activeButton) {
  const tabs = activeButton.closest('.result-tabs');
  if (!tabs) return;
  tabs.querySelectorAll('button').forEach((button) => {
    const active = button === activeButton;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
    button.tabIndex = active ? 0 : -1;
  });
}

function initResultPanels() {
  const tabs = document.querySelector('.result-tabs');
  const stepsPanel = document.querySelector('.steps-panel');
  if (!tabs || !stepsPanel) return;

  if (!$('resultPanel-result')) {
    const resultPanel = document.createElement('section');
    resultPanel.id = 'resultPanel-result';
    resultPanel.className = 'result-tab-panel';
    resultPanel.setAttribute('role', 'tabpanel');
    resultPanel.setAttribute('aria-labelledby', 'resultTab-result');
    stepsPanel.insertAdjacentElement('beforebegin', resultPanel);

    const sourcePanel = document.createElement('section');
    sourcePanel.id = 'resultPanel-source';
    sourcePanel.className = 'result-tab-panel';
    sourcePanel.setAttribute('role', 'tabpanel');
    sourcePanel.setAttribute('aria-labelledby', 'resultTab-source');
    stepsPanel.insertAdjacentElement('afterend', sourcePanel);

    const warningsPanel = document.createElement('section');
    warningsPanel.id = 'resultPanel-warnings';
    warningsPanel.className = 'result-tab-panel';
    warningsPanel.setAttribute('role', 'tabpanel');
    warningsPanel.setAttribute('aria-labelledby', 'resultTab-warnings');
    sourcePanel.insertAdjacentElement('afterend', warningsPanel);
  }

  stepsPanel.id = 'resultPanel-steps';
  stepsPanel.classList.add('result-tab-panel');
  stepsPanel.setAttribute('role', 'tabpanel');
  stepsPanel.setAttribute('aria-labelledby', 'resultTab-steps');

  setResultTab('result');
  updateResultPanels();
}

function setResultTab(name) {
  const target = name || 'result';
  document.querySelectorAll('.result-tabs button').forEach((button) => {
    const active = button.dataset.resultTab === target;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
    button.tabIndex = active ? 0 : -1;
  });

  document.querySelectorAll('.result-tab-panel').forEach((panel) => {
    panel.hidden = panel.id !== 'resultPanel-' + target;
  });
}

function updateResultPanels() {
  updateResultPanel();
  updateSourcePanel();
  updateWarningsPanel();
}

function updateResultPanel() {
  const panel = $('resultPanel-result');
  if (!panel) return;
  panel.textContent = '';

  if (!state.lastRun?.final) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = 'Запустите запрос, чтобы увидеть итоговую точку, формат координат и доступные действия.';
    panel.appendChild(empty);
    return;
  }

  const grid = document.createElement('div');
  grid.className = 'result-summary-grid';
  const fields = [
    ['Итоговые координаты', formatCoord(state.lastRun.final.centroid, $('coordinateFormat')?.value || 'latlon')],
    ['Операция', state.lastRun.final.function || 'Результат'],
    ['Режим', state.lastRun.mode === 'precise' ? 'Точный' : 'Быстрый'],
    ['Экспорт', state.lastRun.geojson ? 'GeoJSON, KML, GPX доступны' : 'Будет доступен после расчета']
  ];
  fields.forEach(([label, value]) => {
    const item = document.createElement('div');
    item.className = 'result-field';
    const key = document.createElement('span');
    key.textContent = label;
    const val = document.createElement('strong');
    val.textContent = value;
    item.append(key, val);
    grid.appendChild(item);
  });
  panel.appendChild(grid);
}

function updateSourcePanel() {
  const panel = $('resultPanel-source');
  if (!panel) return;
  panel.textContent = '';
  if (!state.lastRun) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = 'Здесь появятся исходный запрос, перевод и JSON шагов.';
    panel.appendChild(empty);
    return;
  }
  const pre = document.createElement('pre');
  pre.className = 'source-json';
  pre.textContent = JSON.stringify({
    query: state.lastRun.query,
    translated: state.lastRun.translated || null,
    mode: state.lastRun.mode,
    steps: state.lastRun.steps,
    final: state.lastRun.final,
  }, null, 2);
  panel.appendChild(pre);
}

function updateWarningsPanel() {
  const panel = $('resultPanel-warnings');
  if (!panel) return;
  panel.textContent = '';
  const warnings = state.lastRun?.warnings || [];
  if (!warnings.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = state.lastRun
      ? 'Критических предупреждений по последнему запуску нет. Результат все равно стоит проверять по опорным объектам.'
      : 'Предупреждения появятся после запуска запроса.';
    panel.appendChild(empty);
    return;
  }
  const list = document.createElement('ul');
  list.className = 'warning-list';
  warnings.forEach((warning) => {
    const item = document.createElement('li');
    item.textContent = warning;
    list.appendChild(item);
  });
  panel.appendChild(list);
}

function initShellAnimations() {
  let scrollFrame = null;
  const handleScroll = () => {
    if (scrollFrame) return;
    scrollFrame = window.requestAnimationFrame(() => {
      scrollFrame = null;
      updateScrollProgress();
      updateHeaderScrollState();
    });
  };
  window.addEventListener('scroll', handleScroll, { passive: true });
  updateScrollProgress();
  updateHeaderScrollState();

  const revealItems = document.querySelectorAll('.reveal');
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      entry.target.classList.add('visible');
      observer.unobserve(entry.target);
    });
  }, { threshold: 0.14, rootMargin: '0px 0px -50px 0px' });
  revealItems.forEach((item) => observer.observe(item));

  document.querySelectorAll('[data-count]').forEach(animateCounter);

  initLiquidLight();
}

function initLiquidLight() {
  const fine = window.matchMedia('(hover: hover) and (pointer: fine)');
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  if (!fine.matches || reduced.matches) return;
  const targets = document.querySelectorAll('.btn.primary, .feature-card, .use-case-card, .price-card, [data-tilt-card]');
  targets.forEach((el) => {
    el.classList.add('liquid-light');
    el.addEventListener('pointermove', (event) => {
      const rect = el.getBoundingClientRect();
      el.style.setProperty('--light-x', `${(((event.clientX - rect.left) / rect.width) * 100).toFixed(1)}%`);
      el.style.setProperty('--light-y', `${(((event.clientY - rect.top) / rect.height) * 100).toFixed(1)}%`);
    }, { passive: true });
  });
}

function updateScrollProgress() {
  if (!els.scrollProgress) return;
  const max = document.documentElement.scrollHeight - window.innerHeight;
  const progress = max > 0 ? (window.scrollY / max) * 100 : 0;
  els.scrollProgress.style.width = `${Math.max(0, Math.min(100, progress)).toFixed(2)}%`;
}

function updateHeaderScrollState() {
  document.querySelectorAll('.topbar').forEach((topbar) => {
    topbar.classList.toggle('is-scrolled', window.scrollY > 8 || topbar.classList.contains('nav-open'));
  });
}

function animateCounter(el) {
  const target = Number(el.dataset.count || 0);
  if (!target) return;
  const observer = new IntersectionObserver((entries) => {
    if (!entries[0].isIntersecting) return;
    el.textContent = String(target);
    observer.disconnect();
  }, { threshold: .5 });
  observer.observe(el);
}

function initVisualMaps() {
  if (!window.L) {
    document.querySelectorAll('.visual-map, #map, .account-map').forEach((node) => {
      markMapUnavailable(node, 'Карта не загрузилась', 'Проверьте подключение к сети и обновите страницу.');
    });
    return;
  }
  const heroMap = $('heroMap');
  if (heroMap) {
    const map = L.map(heroMap, {
      attributionControl: true,
      zoomControl: false,
      dragging: false,
      scrollWheelZoom: false,
      doubleClickZoom: false,
      boxZoom: false,
      keyboard: false,
      tap: false
    }).setView([55.84, 49.12], 10);
    addTileLayer(map);
    setupMapPanes(map);

    const derb = [55.8662302, 49.225801];
    const high = [55.9101814, 49.3072048];
    const mid = [55.8882058, 49.2665029];
    L.polyline([derb, high], { className: 'hero-reference-line-shadow', color: '#13212c', weight: 12, opacity: .18, lineCap: 'round' }).addTo(map);
    L.polyline([derb, high], { className: 'hero-reference-line', color: '#0d5eaf', weight: 5, opacity: .94, dashArray: '12 8', lineCap: 'round' }).addTo(map);
    L.circle(mid, {
      radius: 2050,
      color: '#bb762f',
      weight: 3,
      opacity: .88,
      fillColor: '#bb762f',
      fillOpacity: .19,
      className: 'hero-result-zone'
    }).addTo(map);
    L.circleMarker(derb, markerStyle('#6f7a83', 8)).addTo(map);
    L.circleMarker(high, markerStyle('#6f7a83', 8)).addTo(map);
    L.circleMarker(mid, {
      className: 'hero-result-point',
      radius: 18,
      color: '#fffdf8',
      weight: 5,
      fillColor: '#bb762f',
      fillOpacity: 1
    }).addTo(map);
    L.circleMarker(mid, {
      className: 'hero-result-core',
      radius: 5,
      color: '#fffdf8',
      weight: 2,
      fillColor: '#fffdf8',
      fillOpacity: 1
    }).addTo(map);
    map.whenReady(() => {
      heroMap.closest('.hero-visual')?.classList.add('is-map-ready');
    });
  }
}

function initWorkbench() {
  if (!els.queryInput || !els.runBtn) return;
  initWorkbenchMap();
  initDemoEnhancements();

  els.runBtn.addEventListener('click', () => runQuery());
  if (els.saveResultBtn) els.saveResultBtn.addEventListener('click', () => saveCurrentResult());
  if (els.clearBtn) {
    els.clearBtn.addEventListener('click', () => {
      clearMap();
      setStepEmpty();
      setStatus('Карта очищена', 'ready');
      if (els.saveResultBtn) els.saveResultBtn.disabled = true;
      state.lastRun = null;
      updateResultActionState();
      updateResultPanels();
    });
  }

  document.querySelectorAll('.examples button').forEach((button) => {
    button.addEventListener('click', () => {
      els.queryInput.value = button.dataset.query || '';
      els.queryInput.focus();
      updateQueryCounter();
    });
  });

  document.querySelectorAll('[data-export]').forEach((button) => {
    button.addEventListener('click', () => exportCurrentResult(button.dataset.export));
  });
  updateResultActionState();
}

function initDemoEnhancements() {
  updateQueryCounter();
  renderRecentQueries();
  initResultPanels();

  els.queryInput?.addEventListener('input', updateQueryCounter);
  els.clearQueryBtn?.addEventListener('click', () => {
    els.queryInput.value = '';
    els.queryInput.focus();
    updateQueryCounter();
  });

  $('fullscreenMapBtn')?.addEventListener('click', () => {
    const panel = document.querySelector('.map-panel');
    const button = $('fullscreenMapBtn');
    if (!panel) return;
    const opened = panel.classList.toggle('map-fullscreen');
    document.body.classList.toggle('has-map-fullscreen', opened);
    button?.setAttribute('aria-pressed', String(opened));
    button?.setAttribute('aria-label', opened ? 'Закрыть полноэкранную карту' : 'Открыть карту во весь экран');
    const label = button?.querySelector('span');
    if (label) label.textContent = opened ? 'Свернуть карту' : 'Во весь экран';
    if (opened) {
      window.setTimeout(() => state.map?.invalidateSize(), 80);
    } else {
      restoreMapPanelScroll(panel);
    }
  });

  $('returnResultBtn')?.addEventListener('click', () => fitMapToLayers());
  $('copyCoordsBtn')?.addEventListener('click', () => copyCurrentCoords());
  $('openOsmBtn')?.addEventListener('click', () => openCurrentInOsm());
  $('shareResultBtn')?.addEventListener('click', () => shareCurrentQuery());
  $('coordinateFormat')?.addEventListener('change', updateResultPanels);
}

function updateQueryCounter() {
  if (!els.queryCounter || !els.queryInput) return;
  const max = Number(els.queryInput.getAttribute('maxlength') || 500);
  const length = els.queryInput.value.length;
  els.queryCounter.textContent = `${length} / ${max}`;
  els.queryCounter.dataset.warning = length > max * .84 ? 'true' : 'false';
}

function getRecentQueries() {
  if (!canStorePreferences()) return [];
  try {
    const parsed = JSON.parse(localStorage.getItem(RECENT_QUERY_KEY) || '[]');
    return Array.isArray(parsed) ? parsed.filter(Boolean).slice(0, 6) : [];
  } catch (error) {
    return [];
  }
}

function saveRecentQuery(query) {
  if (!query || !canStorePreferences()) return;
  const next = [query, ...getRecentQueries().filter((item) => item !== query)].slice(0, 6);
  localStorage.setItem(RECENT_QUERY_KEY, JSON.stringify(next));
  renderRecentQueries();
}

function renderRecentQueries() {
  if (!els.recentQueries) return;
  const queries = getRecentQueries();
  els.recentQueries.textContent = '';
  if (!queries.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state compact-empty';
    empty.textContent = 'После запуска здесь появятся последние запросы.';
    els.recentQueries.appendChild(empty);
    return;
  }

  queries.forEach((query) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'recent-query';
    button.textContent = query;
    button.addEventListener('click', () => {
      els.queryInput.value = query;
      els.queryInput.focus();
      updateQueryCounter();
    });
    els.recentQueries.appendChild(button);
  });
}

function copyCurrentCoords() {
  const centroid = state.lastRun?.final?.centroid;
  if (!centroid) {
    showToast('Сначала выполните запрос');
    return;
  }
  const value = formatCoord(centroid, $('coordinateFormat')?.value || 'latlon');
  navigator.clipboard?.writeText(value)
    .then(() => showToast('Координаты скопированы'))
    .catch(() => showToast(value));
}

function openCurrentInOsm() {
  const centroid = state.lastRun?.final?.centroid;
  if (!centroid) {
    showToast('Сначала выполните запрос');
    return;
  }
  const [lon, lat] = centroid;
  window.open(`https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=15/${lat}/${lon}`, '_blank', 'noopener');
}

function shareCurrentQuery() {
  const query = els.queryInput?.value.trim();
  if (!query) {
    showToast('Введите запрос для ссылки');
    return;
  }
  const url = new URL(window.location.href);
  url.searchParams.set('q', query);
  navigator.clipboard?.writeText(url.toString())
    .then(() => showToast('Ссылка на запрос скопирована'))
    .catch(() => showToast(url.toString()));
}

function initWorkbenchMap() {
  const mapNode = $('map');
  if (!mapNode) return;
  if (!window.L) {
    markMapUnavailable(mapNode, 'Карта не загрузилась', 'Leaflet или тайлы карты недоступны. Проверьте сеть и обновите страницу.');
    return;
  }
  state.map = L.map(mapNode, {
    attributionControl: true,
    zoomControl: false
  }).setView([55.8304, 49.0661], 10);
  L.control.zoom({ position: 'topright' }).addTo(state.map);
  addTileLayer(state.map);
  setupMapPanes(state.map);
}

function initAccountMap() {
  const mapNode = $('accountMap');
  if (!mapNode) return;
  if (!window.L) {
    markMapUnavailable(mapNode, 'Карта не загрузилась', 'Leaflet или тайлы карты недоступны. Проверьте сеть и обновите страницу.');
    return;
  }
  state.accountMap = L.map(mapNode, {
    attributionControl: true,
    zoomControl: false
  }).setView([55.8304, 49.0661], 9);
  L.control.zoom({ position: 'topright' }).addTo(state.accountMap);
  addTileLayer(state.accountMap);
  setupMapPanes(state.accountMap);
}

function addTileLayer(map) {
  const tileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap'
  }).addTo(map);
  tileLayer.on('tileerror', () => {
    showMapFallback(map, 'Карта временно недоступна', 'Не удалось загрузить тайлы OpenStreetMap. Результаты расчета останутся доступны в координатах и экспорте.');
  });
  tileLayer.on('tileload', () => {
    window.setTimeout(() => clearMapFallback(map), 700);
  });
  return tileLayer;
}

function showMapFallback(map, title, detail) {
  if (!map || !map.getContainer) return;
  markMapUnavailable(map.getContainer(), title, detail);
}

function clearMapFallback(map) {
  if (!map || !map.getContainer) return;
  const container = map.getContainer();
  container.classList.remove('has-map-fallback');
  const panel = container.querySelector('.map-fallback');
  if (panel) panel.hidden = true;
}

function markMapUnavailable(node, title, detail) {
  if (!node) return;
  node.classList.add('has-map-fallback');
  let panel = node.querySelector('.map-fallback');
  if (!panel) {
    panel = document.createElement('div');
    panel.className = 'map-fallback';
    panel.setAttribute('role', 'status');
    panel.setAttribute('aria-live', 'polite');
    panel.innerHTML = '<i data-lucide="map-off"></i><strong></strong><span></span>';
    node.appendChild(panel);
  }
  panel.hidden = false;
  const strong = panel.querySelector('strong');
  const span = panel.querySelector('span');
  if (strong) strong.textContent = title;
  if (span) span.textContent = detail;
  initIcons();
}

function setupMapPanes(map) {
  if (!map || map._spatialParsePanesReady) return;
  [
    ['spZoneHaloPane', 390],
    ['spZonePane', 430],
    ['spReferencePane', 570],
    ['spRoutePane', 650],
    ['spMarkerPane', 760]
  ].forEach(([name, zIndex]) => {
    const pane = map.getPane(name) || map.createPane(name);
    pane.style.zIndex = String(zIndex);
  });
  map._spatialParsePanesReady = true;
}

function paneName(map, name) {
  return map && map.getPane && map.getPane(name) ? name : 'overlayPane';
}

function markerStyle(color, radius = 7) {
  return {
    radius,
    color,
    weight: 3,
    fillColor: '#fffdf8',
    fillOpacity: .95
  };
}

function bindAuth() {
  initAccountMenu();
  enhanceAuthModal();
  enhanceAuthConsent();
  if (els.authOpenBtn) els.authOpenBtn.addEventListener('click', () => openAuth('login'));
  if (els.openAccountBtn) {
    els.openAccountBtn.addEventListener('click', (event) => {
      if (state.token && state.user) {
        toggleAccountMenu(event);
        return;
      }
      if (document.body.dataset.page === 'account') {
        if (!state.token) openAuth('login');
        return;
      }
      window.location.href = 'account.html';
    });
  }
  document.querySelectorAll('[data-open-auth]').forEach((button) => {
    button.addEventListener('click', () => openAuth('login'));
  });
  document.querySelectorAll('[data-close-auth]').forEach((button) => {
    button.addEventListener('click', closeAuth);
  });
  if (els.loginTab) els.loginTab.addEventListener('click', () => setAuthMode('login'));
  if (els.registerTab) els.registerTab.addEventListener('click', () => setAuthMode('register'));
  bindAuthTabs();
  initAuthValidation();
  if (els.loginForm) els.loginForm.addEventListener('submit', handleLogin);
  if (els.registerForm) els.registerForm.addEventListener('submit', handleRegister);
  if (els.logoutBtn) els.logoutBtn.addEventListener('click', logout);
  if (els.refreshHistoryBtn) els.refreshHistoryBtn.addEventListener('click', () => loadAccount());
  if (els.refreshSavedBtn) els.refreshSavedBtn.addEventListener('click', () => loadAccount());

  document.addEventListener('keydown', (event) => {
    const openDialog = document.querySelector('.modal.open');
    if (openDialog && event.key === 'Tab') {
      trapModalFocus(event, openDialog);
    }
    if (event.key === 'Escape') {
      closeMapFullscreen();
      closeConfirmDialog(false);
      closeSaveDialog(null);
      closeAuth();
      closeAccountMenu();
    }
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter' && els.queryInput) runQuery();
  });
}

function initAccountMenu() {
  const actions = document.querySelector('.auth-actions');
  if (!actions) return;
  actions.classList.add('has-account-menu');

  let menu = $('accountMenu');
  if (!menu) {
    menu = document.createElement('div');
    menu.id = 'accountMenu';
    menu.className = 'account-menu';
    menu.hidden = true;
    actions.appendChild(menu);
  }
  els.accountMenu = menu;

  if (els.userChip) {
    els.userChip.setAttribute('role', 'button');
    els.userChip.setAttribute('tabindex', '0');
    els.userChip.setAttribute('aria-haspopup', 'menu');
    els.userChip.setAttribute('aria-expanded', 'false');
    els.userChip.addEventListener('click', toggleAccountMenu);
    els.userChip.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      toggleAccountMenu(event);
    });
  }
  if (els.openAccountBtn) {
    els.openAccountBtn.setAttribute('aria-haspopup', 'menu');
    els.openAccountBtn.setAttribute('aria-expanded', 'false');
  }

  document.addEventListener('click', (event) => {
    if (!els.accountMenu || els.accountMenu.hidden) return;
    if (actions.contains(event.target)) return;
    closeAccountMenu();
  });
}

function toggleAccountMenu(event) {
  if (event) {
    event.preventDefault();
    event.stopPropagation();
  }
  if (!state.token || !state.user || !els.accountMenu) return;
  if (els.accountMenu.hidden) openAccountMenu();
  else closeAccountMenu();
}

function openAccountMenu() {
  if (!els.accountMenu) return;
  renderAccountMenu();
  els.accountMenu.hidden = false;
  if (els.userChip) els.userChip.setAttribute('aria-expanded', 'true');
  if (els.openAccountBtn) els.openAccountBtn.setAttribute('aria-expanded', 'true');
}

function closeAccountMenu() {
  if (els.accountMenu) els.accountMenu.hidden = true;
  if (els.userChip) els.userChip.setAttribute('aria-expanded', 'false');
  if (els.openAccountBtn) els.openAccountBtn.setAttribute('aria-expanded', 'false');
}

function renderAccountMenu() {
  if (!els.accountMenu) return;
  const logged = Boolean(state.token && state.user);
  if (!logged) {
    els.accountMenu.textContent = '';
    closeAccountMenu();
    return;
  }

  const userName = state.user.name || state.user.email || 'Пользователь';
  const email = state.user.email || '';
  const initial = (userName.trim()[0] || 'S').toUpperCase();
  const summary = state.summary || {};
  const historyCount = summary.history_count ?? state.history.length ?? 0;
  const savedCount = summary.saved_count ?? state.saved.length ?? 0;
  const lastActivity = summary.last_activity ? formatDate(summary.last_activity) : '—';

  els.accountMenu.innerHTML = `
    <div class="account-menu-head">
      <span class="account-avatar">${escapeHtml(initial)}</span>
      <span class="account-identity">
        <strong>${escapeHtml(userName)}</strong>
        <small>${escapeHtml(email)}</small>
      </span>
    </div>
    <div class="account-menu-stats" aria-label="Статистика аккаунта">
      <span><b>${escapeHtml(historyCount)}</b><small>запросов</small></span>
      <span><b>${escapeHtml(savedCount)}</b><small>сохранено</small></span>
      <span title="${escapeHtml(lastActivity)}"><b>${escapeHtml(lastActivity)}</b><small>активность</small></span>
    </div>
    <div class="account-menu-list" role="menu" aria-label="Меню аккаунта">
      <a class="account-menu-item" role="menuitem" href="account.html">
        <i data-lucide="layout-dashboard"></i>
        <span><strong>Личный кабинет</strong><small>История, сохранённые точки и карта</small></span>
      </a>
      <a class="account-menu-item" role="menuitem" href="demo.html">
        <i data-lucide="map"></i>
        <span><strong>Новый геозапрос</strong><small>Открыть рабочую карту</small></span>
      </a>
      <a class="account-menu-item" role="menuitem" href="pricing.html">
        <i data-lucide="gauge"></i>
        <span><strong>Тариф и лимиты</strong><small>Текущий план и запросы</small></span>
      </a>
      <a class="account-menu-item" role="menuitem" href="account.html#settings">
        <i data-lucide="user-cog"></i>
        <span><strong>Настройки профиля</strong><small>Регион, радиус и данные аккаунта</small></span>
      </a>
      <a class="account-menu-item" role="menuitem" href="about.html">
        <i data-lucide="life-buoy"></i>
        <span><strong>Помощь</strong><small>О проекте и контакты</small></span>
      </a>
      <button class="account-menu-item danger" role="menuitem" type="button" data-account-action="logout">
        <i data-lucide="log-out"></i>
        <span><strong>Выйти</strong><small>Завершить текущую сессию</small></span>
      </button>
    </div>
  `;

  els.accountMenu.querySelectorAll('a').forEach((link) => {
    link.addEventListener('click', closeAccountMenu);
  });
  els.accountMenu.querySelector('[data-account-action="logout"]')?.addEventListener('click', () => {
    closeAccountMenu();
    logout();
  });
  initIcons();
}

function bindDemoLinks() {
  document.querySelectorAll('[data-demo-query]').forEach((button) => {
    button.addEventListener('click', () => {
      const query = button.dataset.demoQuery || '';
      window.location.href = 'demo.html?q=' + encodeURIComponent(query);
    });
  });
}

function applyQueryParam() {
  if (!els.queryInput) return;
  const params = new URLSearchParams(window.location.search);
  const query = params.get('q');
  if (query) {
    els.queryInput.value = query;
    updateQueryCounter();
  }
}

function applyAuthParam() {
  const params = new URLSearchParams(window.location.search);
  const mode = params.get('auth') || window.location.hash.replace('#', '');
  if (mode === 'register' || mode === 'login') {
    window.setTimeout(() => openAuth(mode), 120);
  }
}

async function apiFetch(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  if (state.token) headers.Authorization = 'Bearer ' + state.token;

  const response = await fetch(API_BASE + path, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = data.detail || data.message || 'HTTP ' + response.status;
    throw new Error(message);
  }
  return data;
}

function setStatus(message, type = 'ready') {
  if (!els.statusText || !els.statusPill) return;
  els.statusText.textContent = message;
  els.statusPill.dataset.type = type;
}

function setRunning(isRunning, status = isRunning ? 'processing' : 'idle') {
  state.isRunning = Boolean(isRunning);
  state.runStatus = status;
  document.body.dataset.runStatus = status;
  document.getElementById('workbench')?.classList.toggle('is-running', Boolean(isRunning));
  if (!els.runBtn) return;
  els.runBtn.disabled = isRunning;
  els.runBtn.classList.toggle('is-loading', isRunning);
  els.runBtn.setAttribute('aria-busy', String(isRunning));
  const label = els.runBtn.querySelector('span');
  if (label) label.textContent = isRunning ? 'Выполняется' : 'Найти на карте';
}

async function runQuery() {
  if (!els.queryInput) return;
  if (state.isRunning) {
    showToast('Запрос уже выполняется');
    return;
  }

  const text = els.queryInput.value.trim();
  if (!text) {
    showToast('Введите запрос');
    return;
  }

  const mode = getMode();
  saveRecentQuery(text);
  clearMap();
  setStepEmpty('Ожидаю шаги от backend...');
  setRunning(true);
  if (els.saveResultBtn) els.saveResultBtn.disabled = true;
  setStatus('Подключение к backend', 'working');

  state.lastRun = {
    query: text,
    mode,
    steps: [],
    results: {},
    final: null,
    geojson: null,
    translated: null,
    warnings: [],
    historySaved: false
  };

  try {
    await runWebSocket(text, mode);
  } catch (error) {
    if (error && error.partial) {
      finishPartialRun(error);
    } else {
      await runRestFallback(text, mode, error);
    }
  }
}

function getMode() {
  const checked = document.querySelector('input[name="mode"]:checked');
  return checked ? checked.value : 'fast';
}

function runWebSocket(text, mode) {
  return new Promise((resolve, reject) => {
    let ws;
    let opened = false;
    let finished = false;
    let settled = false;

    const cleanup = () => {
      window.clearTimeout(openTimeout);
      if (state.runTimeoutId) {
        window.clearTimeout(state.runTimeoutId);
        state.runTimeoutId = null;
      }
      if (state.activeWebSocket === ws) state.activeWebSocket = null;
    };

    const settleReject = (error) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error);
    };

    const settleResolve = () => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve();
    };

    try {
      ws = new WebSocket(WS_URL);
      state.activeWebSocket = ws;
    } catch (error) {
      reject(error);
      return;
    }

    const openTimeout = window.setTimeout(() => {
      if (!opened) {
        try { ws.close(); } catch (error) { /* noop */ }
        settleReject(new Error('WebSocket timeout'));
      }
    }, 4500);

    state.runTimeoutId = window.setTimeout(() => {
      if (finished) return;
      const error = new Error('Превышено время ожидания ответа backend');
      error.partial = Boolean(state.lastRun && Object.keys(state.lastRun.results).length > 0);
      try { ws.close(); } catch (closeError) { /* noop */ }
      settleReject(error);
    }, DEMO_RUN_TIMEOUT_MS);

    ws.onopen = () => {
      opened = true;
      window.clearTimeout(openTimeout);
      state.runStatus = 'parsing';
      setStatus('Анализ текста', 'working');
      ws.send(JSON.stringify({
        text,
        mode,
        uncertainty: Boolean($('uncertaintyToggle') && $('uncertaintyToggle').checked),
        draw_roads: Boolean($('roadsToggle') && $('roadsToggle').checked)
      }));
    };

    ws.onerror = () => {
      if (!finished) settleReject(new Error('WebSocket error'));
    };

    ws.onclose = () => {
      if (!finished) {
        const error = new Error('WebSocket closed before completion');
        error.partial = Boolean(state.lastRun && Object.keys(state.lastRun.results).length > 0);
        settleReject(error);
      }
    };

    ws.onmessage = async (event) => {
      const message = JSON.parse(event.data);
      await handleStreamMessage(message);
      if (message.type === 'complete') {
        finished = true;
        try { ws.close(); } catch (error) { /* noop */ }
        settleResolve();
      }
      if (message.type === 'error') {
        finished = true;
        settleReject(new Error(message.message || 'Backend error'));
      }
    };
  });
}

async function handleStreamMessage(message) {
  switch (message.type) {
    case 'status':
      setStatus(message.message, 'working');
      break;
    case 'translated':
      if (state.lastRun) state.lastRun.translated = message.translated;
      setStatus('Перевод: ' + message.translated, 'working');
      updateResultPanels();
      break;
    case 'steps':
      state.lastRun.steps = message.steps || [];
      renderSteps(state.lastRun.steps);
      state.runStatus = 'processing';
      setStatus('Выполнение шагов', 'working');
      break;
    case 'step_start':
      markStep(message.step_id, 'computing');
      break;
    case 'step_result':
      handleStepResult(message);
      break;
    case 'step_error':
      markStep(message.step_id, 'error', null, message.error || 'Ошибка шага');
      setStatus('Ошибка на шаге ' + message.step_id, 'error');
      break;
    case 'verification':
      if (state.lastRun && !message.plausible) {
        state.lastRun.warnings.push('Автоматическая проверка пометила результат как требующий ручной сверки.');
      }
      setStatus(message.plausible ? 'Результат проверен' : 'Нужна ручная проверка', message.plausible ? 'ready' : 'warning');
      updateResultPanels();
      break;
    case 'complete':
      state.lastRun.geojson = message.geojson || {};
      await finishRun();
      break;
    default:
      break;
  }
}

function handleStepResult(message) {
  const result = message.result || {};
  const stepResult = {
    step_id: message.step_id,
    function: message.function,
    centroid: result.centroid,
    coordinates: result.coordinates || [],
    is_final: Boolean(message.is_final)
  };

  state.lastRun.results[message.step_id] = stepResult;
  if (message.is_final) state.lastRun.final = stepResult;

  markStep(message.step_id, 'done', result);
  addReferencePoints(message.ref_points || []);
  drawReferenceGeometry(message.reference_geometry);
  drawRoadGeometry(message.road_geometry);
  addStepToMap(stepResult);
  fitMapToLayers();
  updateResultPanels();
}

async function runRestFallback(text, mode, originalError) {
  setStatus('WebSocket недоступен, пробую REST', 'warning');
  state.runStatus = 'processing';
  if (state.lastRun) {
    state.lastRun.warnings.push('WebSocket недоступен, расчет выполнен через REST fallback.');
  }
  try {
    const data = await apiFetch('/api/parse', {
      method: 'POST',
      body: JSON.stringify({
        text,
        mode,
        uncertainty: Boolean($('uncertaintyToggle') && $('uncertaintyToggle').checked),
        draw_roads: Boolean($('roadsToggle') && $('roadsToggle').checked)
      })
    });
    renderRestResult(data);
    await finishRun();
  } catch (error) {
    setRunning(false, 'error');
    setStatus('Backend недоступен', 'error');
    const reason = error.message || (originalError && originalError.message) || 'unknown error';
    if (state.lastRun) state.lastRun.warnings.push(reason);
    setStepError('Не удалось выполнить запрос: ' + reason);
    updateResultPanels();
  }
}

function finishPartialRun(error) {
  setRunning(false, 'partial');
  setStatus('Показан частичный результат', 'warning');
  const message = error?.message || 'Соединение закрылось до завершения расчета.';
  if (state.lastRun) {
    state.lastRun.warnings.push(message + ' Можно повторить запрос.');
  }
  setStepError('Расчет прерван до финального сообщения. Уже полученные шаги показаны на карте.');
  fitMapToLayers();
  updateResultActionState();
  updateResultPanels();
  if (els.saveResultBtn) els.saveResultBtn.disabled = true;
}

function renderRestResult(data) {
  state.lastRun.steps = data.steps || [];
  state.lastRun.geojson = data.geojson || {};
  state.lastRun.translated = data.translated || state.lastRun.translated || null;
  renderSteps(state.lastRun.steps);

  const results = data.results || {};
  const roadGeometries = data.road_geometries || {};
  const stepMetadata = data.step_metadata || {};
  state.lastRun.steps.forEach((step, index) => {
    const raw = results[String(step.id)];
    if (!raw) return;
    const metadata = stepMetadata[String(step.id)] || {};
    const isFinal = index === state.lastRun.steps.length - 1;
    const stepResult = {
      step_id: step.id,
      function: step.function,
      centroid: raw.centroid,
      coordinates: raw.coordinates || [],
      is_final: isFinal
    };
    state.lastRun.results[step.id] = stepResult;
    if (isFinal) state.lastRun.final = stepResult;
    markStep(step.id, 'done', raw);
    addReferencePoints(metadata.ref_points || []);
    drawReferenceGeometry(metadata.reference_geometry);
    if (roadGeometries[String(step.id)]) drawRoadGeometry(roadGeometries[String(step.id)]);
    addStepToMap(stepResult);
  });
  fitMapToLayers();
}

async function finishRun() {
  setRunning(false, 'completed');
  setStatus('Готово', 'ready');
  fitMapToLayers();
  updateResultActionState();
  updateResultPanels();
  if (els.saveResultBtn) els.saveResultBtn.disabled = !state.lastRun || !state.lastRun.final;
  if (state.token) await saveRunToHistory();
}

function updateResultActionState() {
  const hasCentroid = Boolean(state.lastRun?.final?.centroid);
  const hasGeojsonFeatures = Boolean(
    state.lastRun?.geojson?.type === 'FeatureCollection' &&
    Array.isArray(state.lastRun.geojson.features) &&
    state.lastRun.geojson.features.length > 0
  );
  ['copyCoordsBtn', 'openOsmBtn', 'returnResultBtn'].forEach((id) => {
    const button = $(id);
    if (button) button.disabled = !hasCentroid;
  });
  document.querySelectorAll('[data-export]').forEach((button) => {
    button.disabled = !hasGeojsonFeatures;
  });
}

async function saveRunToHistory() {
  if (!state.lastRun || state.lastRun.historySaved || !state.token) return;
  state.lastRun.historySaved = true;
  try {
    const response = await apiFetch('/api/history', {
      method: 'POST',
      body: JSON.stringify({
        query: state.lastRun.query,
        mode: state.lastRun.mode,
        steps: state.lastRun.steps,
        geojson: state.lastRun.geojson,
        final: { centroid: state.lastRun.final ? state.lastRun.final.centroid : null }
      })
    });
    state.summary = response.summary || state.summary;
    await loadAccount({ silent: true });
  } catch (error) {
    state.lastRun.historySaved = false;
    showToast('История не сохранена: ' + error.message);
  }
}

async function saveCurrentResult() {
  if (!state.lastRun || !state.lastRun.final) return;
  if (!state.token) {
    openAuth('login');
    showToast('Войдите, чтобы сохранять результаты');
    return;
  }

  const centroid = state.lastRun.final.centroid;
  const defaultTitle = state.lastRun.query.slice(0, 70);
  const title = await requestSaveTitle(defaultTitle);
  if (title === null) return;

  try {
    const response = await apiFetch('/api/saved-places', {
      method: 'POST',
      body: JSON.stringify({
        title: title || defaultTitle,
        query: state.lastRun.query,
        lon: centroid ? centroid[0] : null,
        lat: centroid ? centroid[1] : null,
        geojson: state.lastRun.geojson || {}
      })
    });
    state.summary = response.summary || state.summary;
    showToast('Результат сохранен');
    await loadAccount({ silent: true });
  } catch (error) {
    showToast('Не удалось сохранить: ' + error.message);
  }
}

async function exportCurrentResult(type) {
  if (!state.lastRun || !state.lastRun.geojson) {
    showToast('Сначала выполните запрос');
    return;
  }
  try {
    const response = await fetch(API_BASE + '/api/export/' + type, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ geojson: state.lastRun.geojson })
    });
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const blob = await response.blob();
    triggerDownload(blob, 'spatialparse_result.' + type);
  } catch (error) {
    showToast('Экспорт не выполнен: ' + error.message);
  }
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function renderSteps(steps) {
  if (!els.stepsList) return;
  els.stepsList.textContent = '';
  if (!steps.length) {
    setStepEmpty();
    return;
  }
  steps.forEach((step) => {
    const card = document.createElement('div');
    card.className = 'step-card';
    card.id = 'step-' + step.id;

    const top = document.createElement('div');
    top.className = 'step-top';

    const title = document.createElement('div');
    title.className = 'step-title';
    title.textContent = '#' + step.id + ' ' + step.function;

    const status = document.createElement('div');
    status.className = 'step-status';
    status.textContent = 'ожидание';

    top.append(title, status);

    const meta = document.createElement('div');
    meta.className = 'step-meta';
    meta.textContent = formatInputs(step.inputs || []);

    const coords = document.createElement('div');
    coords.className = 'coords';

    card.append(top, meta, coords);
    els.stepsList.appendChild(card);
  });
}

function markStep(id, status, result, errorText) {
  const card = $('step-' + id);
  if (!card) return;
  card.classList.remove('done', 'error', 'final');
  if (status === 'done') card.classList.add('done');
  if (status === 'error') card.classList.add('error');

  const labels = {
    computing: 'вычисление',
    done: 'готово',
    error: 'ошибка'
  };
  const statusNode = card.querySelector('.step-status');
  if (statusNode) statusNode.textContent = labels[status] || status;

  const coords = card.querySelector('.coords');
  if (coords && result && result.centroid) {
    coords.textContent = formatCoord(result.centroid);
  } else if (coords && errorText) {
    coords.textContent = errorText;
  }

  const lastId = state.lastRun && state.lastRun.final ? state.lastRun.final.step_id : null;
  if (lastId === id) card.classList.add('final');
}

function setStepEmpty(text = 'После запуска здесь появятся операции, координаты и ошибки по шагам.') {
  if (!els.stepsList) return;
  els.stepsList.textContent = '';
  els.stepsList.appendChild(createEmptyState('activity', 'Ожидаю расчет', text));
}

function setStepError(text) {
  if (!els.stepsList) return;
  els.stepsList.textContent = '';
  const card = document.createElement('div');
  card.className = 'step-card error';
  card.textContent = text;
  els.stepsList.appendChild(card);
}

function formatInputs(inputs) {
  return inputs.map((item) => String(item)).join(' -> ');
}

function formatCoord(centroid, format = 'latlon') {
  if (!centroid || centroid.length < 2) return '';
  const lon = Number(centroid[0]).toFixed(6);
  const lat = Number(centroid[1]).toFixed(6);
  return format === 'lonlat' ? `${lon}, ${lat}` : `${lat}, ${lon}`;
}

function clearMap() {
  if (!state.map) return;
  state.layers.forEach((layer) => {
    try { state.map.removeLayer(layer); } catch (error) { /* noop */ }
  });
  state.layers = [];
}

function addLayer(layer) {
  state.layers.push(layer);
  return layer;
}

function addStepToMap(stepResult) {
  if (!state.map || !stepResult.centroid) return;
  const index = Number(stepResult.step_id) - 1;
  const color = stepResult.is_final ? FINAL_COLOR : COLORS[index % COLORS.length];
  const latlng = [stepResult.centroid[1], stepResult.centroid[0]];

  if (Array.isArray(stepResult.coordinates) && stepResult.coordinates.length > 2) {
    const latlngs = toLatLngs(stepResult.coordinates);
    const halo = L.polygon(latlngs, {
      pane: paneName(state.map, 'spZoneHaloPane'),
      className: 'premium-zone premium-zone-halo',
      color,
      weight: 18,
      opacity: .12,
      fillColor: color,
      fillOpacity: stepResult.is_final ? .13 : .08,
      interactive: false
    }).addTo(state.map);
    addLayer(halo);

    const fill = L.polygon(latlngs, {
      pane: paneName(state.map, 'spZonePane'),
      className: 'premium-zone premium-zone-fill',
      color: '#fffdf8',
      weight: 6,
      opacity: .72,
      fillColor: color,
      fillOpacity: stepResult.is_final ? .26 : .15,
      interactive: false
    }).addTo(state.map);
    addLayer(fill);

    const outline = L.polygon(latlngs, {
      pane: paneName(state.map, 'spZonePane'),
      className: 'premium-zone premium-zone-outline',
      color,
      weight: stepResult.is_final ? 3.2 : 2.4,
      opacity: .94,
      fillColor: color,
      fillOpacity: 0,
      dashArray: stepResult.is_final ? null : '9 7',
      lineCap: 'round',
      lineJoin: 'round'
    }).addTo(state.map);
    addLayer(outline);
  }

  const ring = L.circleMarker(latlng, {
    pane: paneName(state.map, 'spMarkerPane'),
    className: 'result-marker-ring',
    radius: stepResult.is_final ? 21 : 17,
    color,
    weight: 2,
    opacity: .28,
    fillColor: color,
    fillOpacity: .08,
    interactive: false
  }).addTo(state.map);
  addLayer(ring);

  const marker = L.marker(latlng, {
    pane: paneName(state.map, 'spMarkerPane'),
    icon: L.divIcon({
      className: 'result-marker',
      html: '<span class="marker-core" style="--marker-color:' + color + '"><b>' + (stepResult.is_final ? '*' : stepResult.step_id) + '</b></span>',
      iconSize: [36, 36],
      iconAnchor: [18, 18]
    })
  }).addTo(state.map);
  marker.bindPopup(
    '<b>Шаг ' + escapeHtml(stepResult.step_id) + ': ' + escapeHtml(stepResult.function || '') + '</b><br>' +
    '<code>' + escapeHtml(formatCoord(stepResult.centroid)) + '</code>'
  );
  addLayer(marker);
}

function addReferencePoints(points) {
  if (!state.map || !Array.isArray(points)) return;
  points.forEach((point) => {
    if (typeof point.lon !== 'number' || typeof point.lat !== 'number') return;
    const marker = L.circleMarker([point.lat, point.lon], {
      pane: paneName(state.map, 'spReferencePane'),
      className: 'reference-point',
      radius: 6,
      color: REF_COLOR,
      weight: 2,
      opacity: .9,
      fillColor: '#fffdf8',
      fillOpacity: .92,
      dashArray: '3 3'
    }).addTo(state.map);
    marker.bindPopup('<b>' + escapeHtml(point.name || 'Опорная точка') + '</b><br><code>' + escapeHtml(formatCoord([point.lon, point.lat])) + '</code>');
    addLayer(marker);
  });
}

function drawReferenceGeometry(points) {
  if (!state.map || !Array.isArray(points) || points.length < 2) return;
  const latlngs = toLatLngs(points);
  const casing = L.polyline(latlngs, {
    pane: paneName(state.map, 'spReferencePane'),
    className: 'reference-line reference-line-casing',
    color: '#fffdf8',
    weight: 6,
    opacity: .82,
    interactive: false
  }).addTo(state.map);
  addLayer(casing);

  const line = L.polyline(latlngs, {
    pane: paneName(state.map, 'spReferencePane'),
    className: 'reference-line',
    color: REF_COLOR,
    weight: 2.4,
    opacity: .84,
    dashArray: '5 8',
    lineCap: 'round',
    lineJoin: 'round'
  }).addTo(state.map);
  addLayer(line);
}

function drawRoadGeometry(points) {
  if (!state.map || !Array.isArray(points) || points.length < 2) return;
  const latlngs = toLatLngs(points);
  const routePane = paneName(state.map, 'spRoutePane');
  const markerPane = paneName(state.map, 'spMarkerPane');
  const shadow = L.polyline(latlngs, {
    pane: routePane,
    className: 'premium-road premium-road-shadow',
    color: '#14202a',
    weight: 13,
    opacity: .18,
    lineCap: 'round',
    lineJoin: 'round',
    interactive: false
  }).addTo(state.map);
  addLayer(shadow);

  const casing = L.polyline(latlngs, {
    pane: routePane,
    className: 'premium-road premium-road-casing',
    color: '#fffdf8',
    weight: 9,
    opacity: .96,
    lineCap: 'round',
    lineJoin: 'round',
    interactive: false
  }).addTo(state.map);
  addLayer(casing);

  const main = L.polyline(latlngs, {
    pane: routePane,
    className: 'premium-road premium-road-main',
    color: '#0d5eaf',
    weight: 5,
    opacity: .96,
    lineCap: 'round',
    lineJoin: 'round'
  }).addTo(state.map);
  addLayer(main);

  const flow = L.polyline(latlngs, {
    pane: routePane,
    className: 'premium-road premium-road-flow',
    color: '#7ff0c9',
    weight: 2,
    opacity: .92,
    dashArray: '1 14',
    lineCap: 'round',
    lineJoin: 'round',
    interactive: false
  }).addTo(state.map);
  addLayer(flow);

  [latlngs[0], latlngs[latlngs.length - 1]].forEach((latlng, idx) => {
    const terminal = L.circleMarker(latlng, {
      pane: markerPane,
      className: idx === 0 ? 'road-terminal road-terminal-start' : 'road-terminal road-terminal-end',
      radius: idx === 0 ? 6 : 7,
      color: '#fffdf8',
      weight: 3,
      opacity: .98,
      fillColor: idx === 0 ? '#0d5eaf' : '#0c8177',
      fillOpacity: .96
    }).addTo(state.map);
    addLayer(terminal);
  });
}

function toLatLngs(points) {
  return points
    .filter((point) => Array.isArray(point) && point.length >= 2)
    .map((point) => [Number(point[1]), Number(point[0])]);
}

function fitMapToLayers() {
  if (!state.map || state.layers.length === 0) return;
  try {
    const group = L.featureGroup(state.layers);
    const bounds = group.getBounds();
    if (bounds.isValid()) state.map.fitBounds(bounds.pad(.24), { animate: true, duration: .45 });
  } catch (error) {
    /* Ignore empty or invalid Leaflet groups. */
  }
}

function drawGeoJson(geojson, centroid) {
  const targetMap = state.accountMap || state.map;
  if (!targetMap) return;
  const layers = targetMap === state.accountMap ? state.accountLayers : state.layers;
  layers.forEach((layer) => {
    try { targetMap.removeLayer(layer); } catch (error) { /* noop */ }
  });
  if (targetMap === state.accountMap) state.accountLayers = [];
  else state.layers = [];

  const nextLayers = [];
  if (geojson && Array.isArray(geojson.features) && geojson.features.length) {
    const layer = L.geoJSON(geojson, {
      style: () => ({
        pane: paneName(targetMap, 'spZonePane'),
        className: 'premium-zone premium-zone-fill',
        color: FINAL_COLOR,
        weight: 3,
        fillColor: FINAL_COLOR,
        fillOpacity: .18
      }),
      pointToLayer: (_feature, latlng) => L.circleMarker(latlng, {
        pane: paneName(targetMap, 'spMarkerPane'),
        className: 'reference-point',
        radius: 8,
        color: FINAL_COLOR,
        fillColor: FINAL_COLOR,
        fillOpacity: .82
      })
    }).addTo(targetMap);
    nextLayers.push(layer);
  }
  if (centroid && centroid.length >= 2) {
    const marker = L.marker([centroid[1], centroid[0]]).addTo(targetMap);
    marker.bindPopup('<b>Сохраненный результат</b><br><code>' + escapeHtml(formatCoord(centroid)) + '</code>');
    nextLayers.push(marker);
  }
  if (targetMap === state.accountMap) state.accountLayers = nextLayers;
  else state.layers = nextLayers;

  try {
    const group = L.featureGroup(nextLayers);
    const bounds = group.getBounds();
    if (bounds.isValid()) targetMap.fitBounds(bounds.pad(.24), { animate: true, duration: .45 });
  } catch (error) {
    /* noop */
  }
}

async function handleLogin(event) {
  event.preventDefault();
  clearAuthValidation(els.loginForm);
  const formData = new FormData(els.loginForm);
  try {
    const response = await apiFetch('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({
        email: formData.get('email'),
        password: formData.get('password')
      })
    });
    saveSession(response);
    closeAuth();
    showToast('Вход выполнен');
  } catch (error) {
    showAuthError(els.loginForm, error.message);
  }
}

async function handleRegister(event) {
  event.preventDefault();
  clearAuthValidation(els.registerForm);
  const formData = new FormData(els.registerForm);
  const repeatInput = els.registerForm.querySelector('input[name="password_repeat"]');
  if (repeatInput && repeatInput.value !== formData.get('password')) {
    repeatInput.setAttribute('aria-invalid', 'true');
    repeatInput.setAttribute('aria-describedby', 'authMessage');
    setAuthMessage('Пароли не совпадают');
    repeatInput.focus();
    return;
  }
  try {
    const response = await apiFetch('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({
        name: formData.get('name'),
        email: formData.get('email'),
        password: formData.get('password'),
        consent_accepted: formData.get('consent') === 'on',
        consent_version: CONSENT_DOCUMENT_VERSION
      })
    });
    saveSession(response);
    closeAuth();
    showToast('Аккаунт создан');
  } catch (error) {
    showAuthError(els.registerForm, error.message);
  }
}

function readCachedUser() {
  if (!localStorage.getItem('spatialparse_token')) return null;
  try {
    return JSON.parse(localStorage.getItem('spatialparse_user') || 'null');
  } catch (error) {
    return null;
  }
}

function cacheUser(user) {
  if (user) localStorage.setItem('spatialparse_user', JSON.stringify({ name: user.name || '', email: user.email || '' }));
  else localStorage.removeItem('spatialparse_user');
}

function saveSession(response) {
  state.token = response.token || '';
  state.user = response.user || null;
  state.summary = response.summary || null;
  if (state.token) localStorage.setItem('spatialparse_token', state.token);
  cacheUser(state.user);
  renderAuthState();
  loadAccount();
}

function abortAccountLoad() {
  if (!state.accountAbortController) return;
  state.accountAbortController.abort();
  state.accountAbortController = null;
}

async function logout() {
  abortAccountLoad();
  try {
    await apiFetch('/api/auth/logout', { method: 'POST' });
  } catch (error) {
    /* Logout must still work locally if backend is unavailable. */
  }
  state.token = '';
  state.user = null;
  state.summary = null;
  localStorage.removeItem('spatialparse_token');
  cacheUser(null);
  closeAccountMenu();
  renderAuthState();
  renderGuestAccount();
  showToast('Вы вышли из аккаунта');
}

function renderAuthState() {
  const logged = Boolean(state.token && state.user);
  document.body.classList.toggle('is-authenticated', logged);
  if (els.authOpenBtn) els.authOpenBtn.hidden = logged;
  if (els.logoutBtn) els.logoutBtn.hidden = !logged;
  if (els.userChip) {
    els.userChip.hidden = !logged;
    if (logged) {
      const accountLabel = state.user.name || state.user.email;
      els.userChip.textContent = accountLabel;
      els.userChip.dataset.initial = (accountLabel.trim()[0] || 'S').toUpperCase();
      els.userChip.title = accountLabel;
    } else {
      delete els.userChip.dataset.initial;
      els.userChip.removeAttribute('title');
    }
  }
  renderAccountMenu();
  if (!logged) closeAccountMenu();
  if (els.accountGuest) els.accountGuest.hidden = logged;
  if (els.accountDashboard) els.accountDashboard.hidden = !logged;
  if (logged && state.accountMap) {
    window.setTimeout(() => state.accountMap.invalidateSize(), 80);
  }
}

async function loadAccount(options = {}) {
  if (!state.token) {
    renderGuestAccount();
    return;
  }
  abortAccountLoad();
  const tokenAtStart = state.token;
  const controller = new AbortController();
  state.accountAbortController = controller;
  try {
    const me = await apiFetch('/api/auth/me', { signal: controller.signal });
    if (controller.signal.aborted || state.token !== tokenAtStart) return;
    state.user = me.user;
    state.summary = me.summary;
    cacheUser(state.user);
    renderAuthState();
    renderSummary();

    const [history, saved] = await Promise.all([
      apiFetch('/api/history?limit=30', { signal: controller.signal }),
      apiFetch('/api/saved-places', { signal: controller.signal })
    ]);
    if (controller.signal.aborted || state.token !== tokenAtStart) return;
    state.history = history.items || [];
    state.saved = saved.items || [];
    renderHistory();
    renderSaved();
    renderSummary();
  } catch (error) {
    if (error.name === 'AbortError') return;
    if (state.token !== tokenAtStart) return;
    state.token = '';
    localStorage.removeItem('spatialparse_token');
    cacheUser(null);
    renderAuthState();
    renderGuestAccount();
    if (!options.silent) showToast('Сессия истекла, войдите снова');
  } finally {
    if (state.accountAbortController === controller) {
      state.accountAbortController = null;
    }
  }
}

function renderGuestAccount() {
  state.history = [];
  state.saved = [];
  if (els.accountGuest) els.accountGuest.hidden = false;
  if (els.accountDashboard) els.accountDashboard.hidden = true;
}

function renderSummary() {
  const summary = state.summary || {};
  if (els.historyCount) els.historyCount.textContent = String(summary.history_count || state.history.length || 0);
  if (els.savedCount) els.savedCount.textContent = String(summary.saved_count || state.saved.length || 0);
  if (els.lastActivity) els.lastActivity.textContent = summary.last_activity ? formatDate(summary.last_activity) : '-';
  const historyMirror = $('historyCountMirror');
  const savedMirror = $('savedCountMirror');
  const profileName = $('profileName');
  const profileEmail = $('profileEmail');
  if (historyMirror) historyMirror.textContent = String(summary.history_count || state.history.length || 0);
  if (savedMirror) savedMirror.textContent = String(summary.saved_count || state.saved.length || 0);
  if (profileName && state.user && !profileName.value) profileName.value = state.user.name || '';
  if (profileEmail && state.user && !profileEmail.value) profileEmail.value = state.user.email || '';
  renderAccountMenu();
}

function renderHistory() {
  if (!els.historyList) return;
  els.historyList.textContent = '';
  const query = $('historySearch')?.value.trim().toLowerCase() || '';
  const sortSelect = document.querySelector('#history .account-tools select');
  let items = [...state.history];
  if (query) {
    items = items.filter((item) => String(item.query || '').toLowerCase().includes(query));
  }
  if (sortSelect?.selectedIndex === 1) items.reverse();

  if (!state.history.length) {
    appendEmpty(els.historyList, 'История пока пустая. Запустите запрос после входа.');
    return;
  }
  if (!items.length) {
    appendEmpty(els.historyList, 'По этому поиску ничего не найдено.');
    return;
  }

  items.forEach((item) => {
    els.historyList.appendChild(createListItem(item, [
      ['Повторить', () => openQueryInDemo(item.query, true)],
      ['Показать', () => drawGeoJson(item.geojson, item.centroid)],
      ['Удалить', () => deleteHistory(item.id)]
    ]));
  });
}

function renderSaved() {
  if (!els.savedList) return;
  els.savedList.textContent = '';
  if (!state.saved.length) {
    appendEmpty(els.savedList, 'Сохраненных результатов пока нет.');
    return;
  }
  state.saved.forEach((item) => {
    els.savedList.appendChild(createListItem({
      ...item,
      query: item.title || item.query
    }, [
      ['Показать', () => drawGeoJson(item.geojson, item.centroid)],
      ['В демо', () => openQueryInDemo(item.query || item.title || '', false)],
      ['Удалить', () => deleteSaved(item.id)]
    ]));
  });
}

function openQueryInDemo(query, autorun) {
  if (els.queryInput) {
    els.queryInput.value = query;
    document.getElementById('workbench')?.scrollIntoView({ behavior: 'auto' });
    if (autorun) runQuery();
    return;
  }
  const params = new URLSearchParams({ q: query });
  window.location.href = 'demo.html?' + params.toString();
}

function createListItem(item, actions) {
  const root = document.createElement('article');
  root.className = 'list-item';

  const top = document.createElement('div');
  top.className = 'list-top';

  const title = document.createElement('div');
  title.className = 'list-title';
  title.textContent = item.query || item.title || 'Без названия';

  const date = document.createElement('div');
  date.className = 'list-meta';
  date.textContent = item.created_at ? formatDate(item.created_at) : '';

  top.append(title, date);

  const meta = document.createElement('div');
  meta.className = 'list-meta';
  meta.textContent = item.centroid ? formatCoord(item.centroid) : 'Координаты не сохранены';

  const actionRow = document.createElement('div');
  actionRow.className = 'list-actions';
  actions.forEach(([label, handler]) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'mini-btn';
    button.textContent = label;
    button.addEventListener('click', handler);
    actionRow.appendChild(button);
  });

  root.append(top, meta, actionRow);
  return root;
}

function appendEmpty(parent, text) {
  const title = text.includes('История') ? 'Истории пока нет' : text.includes('Сохран') ? 'Сохранений пока нет' : 'Ничего не найдено';
  parent.appendChild(createEmptyState('inbox', title, text));
}

function createEmptyState(icon, title, detail) {
  const empty = document.createElement('div');
  empty.className = 'empty-state';
  empty.innerHTML = '<i data-lucide="' + icon + '"></i><strong></strong><span></span>';
  empty.querySelector('strong').textContent = title;
  empty.querySelector('span').textContent = detail;
  window.setTimeout(initIcons, 0);
  return empty;
}

async function deleteHistory(id) {
  try {
    const response = await apiFetch('/api/history/' + id, { method: 'DELETE' });
    state.summary = response.summary || state.summary;
    await loadAccount({ silent: true });
  } catch (error) {
    showToast('Не удалось удалить запись');
  }
}

async function deleteSaved(id) {
  try {
    const response = await apiFetch('/api/saved-places/' + id, { method: 'DELETE' });
    state.summary = response.summary || state.summary;
    await loadAccount({ silent: true });
  } catch (error) {
    showToast('Не удалось удалить результат');
  }
}

async function saveAccountSettings() {
  if (!state.token) {
    openAuth('login');
    return;
  }

  const prefs = {
    defaultRegion: $('defaultRegion')?.value.trim() || 'Казань, Татарстан',
    defaultRadius: $('defaultRadius')?.value || '120',
    defaultMode: $('defaultMode')?.value || 'Быстро',
    mapStyle: $('mapStyle')?.value || 'OpenStreetMap',
    updated_at: new Date().toISOString()
  };
  localStorage.setItem(ACCOUNT_PREFS_KEY, JSON.stringify(prefs));

  const nextName = $('profileName')?.value.trim();
  try {
    if (nextName && nextName !== state.user?.name) {
      const response = await apiFetch('/api/account/profile', {
        method: 'PATCH',
        body: JSON.stringify({ name: nextName })
      });
      state.user = response.user || state.user;
      state.summary = response.summary || state.summary;
      renderAuthState();
      renderSummary();
    }
    showToast('Настройки сохранены');
  } catch (error) {
    showToast('Не удалось сохранить настройки: ' + error.message);
  }
}

async function exportAccountData() {
  if (!state.token) {
    openAuth('login');
    showToast('Войдите, чтобы экспортировать данные');
    return;
  }
  try {
    const response = await fetch(API_BASE + '/api/account/export', {
      headers: { Authorization: 'Bearer ' + state.token }
    });
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const blob = await response.blob();
    triggerDownload(blob, 'spatialparse_account_export.json');
    showToast('Экспорт аккаунта подготовлен');
  } catch (error) {
    showToast('Экспорт не выполнен: ' + error.message);
  }
}

async function clearAccountHistory() {
  if (!state.token) {
    openAuth('login');
    return;
  }
  const confirmed = await requestConfirm({
    title: 'Очистить историю?',
    message: 'Будут удалены все записи истории запросов. Сохраненные результаты останутся в кабинете.',
    confirmText: 'Очистить историю',
    tone: 'danger'
  });
  if (!confirmed) return;
  try {
    const response = await apiFetch('/api/history', { method: 'DELETE' });
    state.summary = response.summary || state.summary;
    state.history = [];
    renderHistory();
    renderSummary();
    showToast('История очищена');
  } catch (error) {
    showToast('Не удалось очистить историю: ' + error.message);
  }
}

async function deleteAccount() {
  if (!state.token) {
    openAuth('login');
    return;
  }
  const confirmed = await requestConfirm({
    title: 'Удалить аккаунт?',
    message: 'Будут удалены профиль, история запросов и сохраненные результаты. Действие нельзя отменить.',
    confirmText: 'Удалить аккаунт',
    tone: 'danger'
  });
  if (!confirmed) return;
  try {
    abortAccountLoad();
    await apiFetch('/api/account', { method: 'DELETE' });
    state.token = '';
    state.user = null;
    state.summary = null;
    state.history = [];
    state.saved = [];
    localStorage.removeItem('spatialparse_token');
    cacheUser(null);
    renderAuthState();
    renderGuestAccount();
    showToast('Аккаунт удален');
  } catch (error) {
    showToast('Не удалось удалить аккаунт: ' + error.message);
  }
}

function openAuth(mode = 'login') {
  if (!els.authModal) return;
  state.authReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  setAuthMode(mode);
  clearAuthValidation(els.loginForm);
  clearAuthValidation(els.registerForm);
  els.authModal.classList.remove('closing');
  els.authModal.classList.add('open');
  els.authModal.setAttribute('aria-hidden', 'false');
  setPageInert(true);
  window.setTimeout(() => {
    const selector = mode === 'register'
      ? '#registerForm input[name="name"]'
      : '#loginForm input[name="email"]';
    const target = els.authModal.querySelector(selector) || getFocusable(els.authModal)[0];
    target?.focus();
  }, 30);
}

function closeAuth() {
  if (!els.authModal) return;
  const wasOpen = els.authModal.classList.contains('open');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (wasOpen && !reduceMotion) {
    els.authModal.classList.add('closing');
    window.setTimeout(() => {
      els.authModal.classList.remove('open', 'closing');
    }, 170);
  } else {
    els.authModal.classList.remove('open', 'closing');
  }
  els.authModal.setAttribute('aria-hidden', 'true');
  clearAuthValidation(els.loginForm);
  clearAuthValidation(els.registerForm);
  setPageInert(false);
  if (wasOpen && state.authReturnFocus && document.contains(state.authReturnFocus)) {
    state.authReturnFocus.focus();
  }
}

function setAuthMode(mode) {
  const isLogin = mode === 'login';
  const isReset = mode === 'reset';
  const card = els.authModal?.querySelector('.modal-card');
  clearAuthValidation(els.loginForm);
  clearAuthValidation(els.registerForm);
  if (els.loginTab) els.loginTab.classList.toggle('active', isLogin);
  if (els.registerTab) els.registerTab.classList.toggle('active', !isLogin && !isReset);
  if (els.loginForm) els.loginForm.hidden = !isLogin;
  if (els.registerForm) els.registerForm.hidden = isLogin || isReset;
  const resetForm = $('resetForm');
  if (resetForm) {
    resetForm.hidden = !isReset;
    if (!isReset) resetForm.querySelector('.auth-reset-done')?.remove();
  }
  const authTabs = els.authModal?.querySelector('.auth-tabs');
  if (authTabs) authTabs.hidden = isReset;
  const authTitle = $('authTitle');
  if (authTitle) {
    authTitle.textContent = isReset
      ? 'Восстановление пароля'
      : (isLogin ? 'Вход в SpatialParse' : 'Создание аккаунта');
  }
  if (isReset) {
    window.setTimeout(() => resetForm?.querySelector('input')?.focus(), 30);
  }
  if (card) {
    card.dataset.authMode = isLogin ? 'login' : 'register';
    delete card.dataset.authDirection;
    card.classList.remove('auth-switching');
  }
  if (els.loginTab) {
    els.loginTab.setAttribute('role', 'tab');
    els.loginTab.setAttribute('aria-selected', String(isLogin));
    els.loginTab.setAttribute('aria-controls', 'loginForm');
    els.loginTab.tabIndex = isLogin ? 0 : -1;
  }
  if (els.registerTab) {
    els.registerTab.setAttribute('role', 'tab');
    els.registerTab.setAttribute('aria-selected', String(!isLogin));
    els.registerTab.setAttribute('aria-controls', 'registerForm');
    els.registerTab.tabIndex = isLogin ? -1 : 0;
  }
  const tabs = document.querySelector('.auth-tabs');
  if (tabs) {
    tabs.setAttribute('role', 'tablist');
    tabs.setAttribute('aria-label', 'Режим авторизации');
  }
  if (els.loginForm) {
    els.loginForm.setAttribute('role', 'tabpanel');
    els.loginForm.setAttribute('aria-labelledby', 'loginTab');
  }
  if (els.registerForm) {
    els.registerForm.setAttribute('role', 'tabpanel');
    els.registerForm.setAttribute('aria-labelledby', 'registerTab');
  }
}

function bindAuthTabs() {
  const tabs = [els.loginTab, els.registerTab].filter(Boolean);
  tabs.forEach((tab, index) => {
    if (tab.dataset.authTabReady) return;
    tab.dataset.authTabReady = 'true';
    tab.addEventListener('keydown', (event) => {
      const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End'];
      if (!keys.includes(event.key)) return;
      event.preventDefault();
      let nextIndex = index;
      if (event.key === 'ArrowLeft') nextIndex = index === 0 ? tabs.length - 1 : index - 1;
      if (event.key === 'ArrowRight') nextIndex = index === tabs.length - 1 ? 0 : index + 1;
      if (event.key === 'Home') nextIndex = 0;
      if (event.key === 'End') nextIndex = tabs.length - 1;
      const next = tabs[nextIndex];
      setAuthMode(next === els.registerTab ? 'register' : 'login');
      next?.focus();
    });
  });
}

function initAuthValidation() {
  if (els.authMessage) {
    els.authMessage.setAttribute('role', 'alert');
    els.authMessage.setAttribute('aria-live', 'assertive');
    els.authMessage.setAttribute('aria-atomic', 'true');
    setAuthMessage('');
  }
  [els.loginForm, els.registerForm].filter(Boolean).forEach((form) => {
    if (form.dataset.authValidationReady) return;
    form.dataset.authValidationReady = 'true';
    form.querySelectorAll('input').forEach((input) => {
      input.addEventListener('input', () => {
        input.removeAttribute('aria-invalid');
        if (input.getAttribute('aria-describedby') === 'authMessage') {
          input.removeAttribute('aria-describedby');
        }
        if (form.querySelectorAll('[aria-invalid="true"]').length === 0) setAuthMessage('');
      });
      input.addEventListener('invalid', () => {
        input.setAttribute('aria-invalid', 'true');
        input.setAttribute('aria-describedby', 'authMessage');
      });
    });
  });
}

function setAuthMessage(message) {
  if (!els.authMessage) return;
  els.authMessage.textContent = message || '';
  els.authMessage.hidden = !message;
}

function clearAuthValidation(form) {
  setAuthMessage('');
  form?.querySelectorAll('[aria-invalid="true"]').forEach((input) => {
    input.removeAttribute('aria-invalid');
    if (input.getAttribute('aria-describedby') === 'authMessage') {
      input.removeAttribute('aria-describedby');
    }
  });
}

function authErrorField(form, message) {
  const normalized = String(message || '').toLowerCase();
  if (normalized.includes('email') || normalized.includes('почт') || normalized.includes('пользователь')) {
    return form?.querySelector('input[name="email"]');
  }
  if (normalized.includes('парол')) return form?.querySelector('input[name="password"]');
  if (normalized.includes('соглас')) return form?.querySelector('input[name="consent"]');
  return form?.querySelector('input');
}

function showAuthError(form, message) {
  setAuthMessage(message || 'Не удалось выполнить действие');
  const field = authErrorField(form, message);
  if (field) {
    field.setAttribute('aria-invalid', 'true');
    field.setAttribute('aria-describedby', 'authMessage');
    field.focus();
  }
}

function ensureSaveModal() {
  let modal = $('saveModal');
  if (modal) return modal;

  modal = document.createElement('div');
  modal.className = 'modal save-modal';
  modal.id = 'saveModal';
  modal.setAttribute('aria-hidden', 'true');
  modal.innerHTML = `
    <div class="modal-backdrop" data-save-cancel></div>
    <div class="modal-card save-modal-card" role="dialog" aria-modal="true" aria-labelledby="saveTitle">
      <button class="icon-btn modal-close" type="button" data-save-cancel aria-label="Закрыть"><i data-lucide="x"></i></button>
      <h2 id="saveTitle">Сохранить результат</h2>
      <p class="modal-sub">Название будет видно в кабинете, истории и экспортируемых данных.</p>
      <form class="save-form" id="saveForm">
        <label><span>Название</span><input id="saveTitleInput" name="title" type="text" maxlength="120" autocomplete="off" required></label>
        <div class="save-form-actions">
          <button class="btn secondary" type="button" data-save-cancel>Отмена</button>
          <button class="btn primary" type="submit"><i data-lucide="bookmark-plus"></i><span>Сохранить</span></button>
        </div>
      </form>
    </div>
  `;
  document.body.appendChild(modal);
  modal.querySelector('#saveForm')?.addEventListener('submit', (event) => {
    event.preventDefault();
    const input = $('saveTitleInput');
    closeSaveDialog(input?.value.trim() || input?.defaultValue || 'Сохраненный результат');
  });
  modal.querySelectorAll('[data-save-cancel]').forEach((button) => {
    button.addEventListener('click', () => closeSaveDialog(null));
  });
  initIcons();
  return modal;
}

function requestSaveTitle(defaultTitle) {
  return new Promise((resolve) => {
    const modal = ensureSaveModal();
    const input = $('saveTitleInput');
    state.saveDialogResolve = resolve;
    state.saveReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (input) {
      input.value = defaultTitle || '';
      input.defaultValue = defaultTitle || 'Сохраненный результат';
    }
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    setPageInert(true, modal);
    window.setTimeout(() => {
      input?.focus();
      input?.select();
    }, 30);
  });
}

function closeSaveDialog(value) {
  const modal = $('saveModal');
  if (!modal || !modal.classList.contains('open')) return;
  modal.classList.remove('open');
  modal.setAttribute('aria-hidden', 'true');
  setPageInert(false, modal);
  const resolve = state.saveDialogResolve;
  state.saveDialogResolve = null;
  if (state.saveReturnFocus && document.contains(state.saveReturnFocus)) {
    state.saveReturnFocus.focus();
  }
  if (resolve) resolve(value);
}

function ensureConfirmModal() {
  let modal = $('confirmModal');
  if (modal) return modal;

  modal = document.createElement('div');
  modal.className = 'modal confirm-modal';
  modal.id = 'confirmModal';
  modal.setAttribute('aria-hidden', 'true');
  modal.innerHTML = `
    <div class="modal-backdrop" data-confirm-cancel></div>
    <div class="modal-card confirm-modal-card" role="dialog" aria-modal="true" aria-labelledby="confirmTitle" aria-describedby="confirmMessage">
      <button class="icon-btn modal-close" type="button" data-confirm-cancel aria-label="Закрыть"><i data-lucide="x"></i></button>
      <span class="confirm-icon"><i data-lucide="triangle-alert"></i></span>
      <h2 id="confirmTitle">Подтвердить действие</h2>
      <p class="modal-sub" id="confirmMessage">Это действие требует подтверждения.</p>
      <div class="confirm-actions">
        <button class="btn secondary" type="button" data-confirm-cancel>Отмена</button>
        <button class="btn primary" type="button" data-confirm-action><i data-lucide="check"></i><span>Подтвердить</span></button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
  modal.querySelectorAll('[data-confirm-cancel]').forEach((button) => {
    button.addEventListener('click', () => closeConfirmDialog(false));
  });
  modal.querySelector('[data-confirm-action]')?.addEventListener('click', () => closeConfirmDialog(true));
  initIcons();
  return modal;
}

function requestConfirm({ title, message, confirmText = 'Подтвердить', tone = 'default' }) {
  return new Promise((resolve) => {
    const modal = ensureConfirmModal();
    const titleEl = $('confirmTitle');
    const messageEl = $('confirmMessage');
    const action = modal.querySelector('[data-confirm-action]');
    const icon = modal.querySelector('.confirm-icon');
    if (titleEl) titleEl.textContent = title || 'Подтвердить действие';
    if (messageEl) messageEl.textContent = message || 'Это действие требует подтверждения.';
    if (action) {
      action.querySelector('span').textContent = confirmText;
      action.classList.toggle('danger', tone === 'danger');
    }
    if (icon) icon.classList.toggle('danger', tone === 'danger');
    state.confirmDialogResolve = resolve;
    state.confirmReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    setPageInert(true, modal);
    window.setTimeout(() => {
      modal.querySelector('.confirm-actions button[data-confirm-cancel]')?.focus();
    }, 30);
  });
}

function closeConfirmDialog(value) {
  const modal = $('confirmModal');
  if (!modal || !modal.classList.contains('open')) return;
  modal.classList.remove('open');
  modal.setAttribute('aria-hidden', 'true');
  setPageInert(false, modal);
  const resolve = state.confirmDialogResolve;
  state.confirmDialogResolve = null;
  if (state.confirmReturnFocus && document.contains(state.confirmReturnFocus)) {
    state.confirmReturnFocus.focus();
  }
  if (resolve) resolve(Boolean(value));
}

function showToast(message) {
  if (!els.toast) return;
  els.toast.textContent = message;
  els.toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    els.toast.hidden = true;
  }, 3200);
}

function getFocusable(root) {
  return Array.from(root.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'))
    .filter((el) => !el.hidden && el.offsetParent !== null);
}

function trapModalFocus(event, modal) {
  if (!modal) return;
  const focusable = getFocusable(modal);
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function setPageInert(active, activeModal = els.authModal) {
  document.body.querySelectorAll(':scope > *').forEach((node) => {
    if (node === activeModal || node === els.toast) return;
    if (node.classList?.contains('modal')) return;
    if (active) {
      node.setAttribute('aria-hidden', 'true');
      node.inert = true;
      node.dataset.spInert = 'true';
    } else {
      if (node.dataset.spInert === 'true') {
        node.removeAttribute('aria-hidden');
        node.inert = false;
        delete node.dataset.spInert;
      }
    }
  });
}

function closeMapFullscreen() {
  const panel = document.querySelector('.map-panel.map-fullscreen');
  if (!panel) return;
  panel.classList.remove('map-fullscreen');
  document.body.classList.remove('has-map-fullscreen');
  const button = $('fullscreenMapBtn');
  button?.setAttribute('aria-pressed', 'false');
  button?.setAttribute('aria-label', 'Открыть карту во весь экран');
  const label = button?.querySelector('span');
  if (label) label.textContent = 'Во весь экран';
  restoreMapPanelScroll(panel);
}

function restoreMapPanelScroll(panel) {
  panel.setAttribute('tabindex', '-1');
  panel.focus({ preventScroll: true });
  const alignToolbar = () => {
    const anchor = panel.querySelector('.map-toolbar') || panel;
    const rect = anchor.getBoundingClientRect();
    const topbarHeight = document.querySelector('.topbar')?.getBoundingClientRect().height || 64;
    const topOffset = topbarHeight + 14;
    window.scrollTo({
      top: Math.max(0, window.scrollY + rect.top - topOffset),
      behavior: 'auto'
    });
  };

  window.requestAnimationFrame(() => {
    window.setTimeout(() => {
      alignToolbar();
      window.setTimeout(() => {
        alignToolbar();
        state.map?.invalidateSize();
      }, 120);
    }, 80);
  });
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(date);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}
