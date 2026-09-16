import { useEffect, useState } from 'react'

const STORAGE_KEY = 'ai-cad-theme'
type Theme = 'dark' | 'light'

/**
 * Theme switch per tokens.css: :root is the dark "drafting board" default;
 * html[data-theme="light"] is the light "drawing office".
 */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() =>
    localStorage.getItem(STORAGE_KEY) === 'light' ? 'light' : 'dark',
  )

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'light') root.dataset.theme = 'light'
    else delete root.dataset.theme
    localStorage.setItem(STORAGE_KEY, theme)
  }, [theme])

  return (
    <button
      type="button"
      onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
      aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
      className="inline-flex items-center gap-1.5 rounded-sheet border border-stroke-hairline px-2 py-1 text-2xs font-medium tracking-label text-ink-tertiary uppercase transition-colors hover:border-stroke-strong hover:text-ink-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      data-testid="theme-toggle"
    >
      <span aria-hidden>◐</span>
      {theme}
    </button>
  )
}
