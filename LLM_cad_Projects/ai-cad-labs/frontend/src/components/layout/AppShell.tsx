import { Outlet } from 'react-router-dom'
import { RotateCw } from 'lucide-react'
import { ThemeToggle } from '@/components/ThemeToggle'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { ProjectPicker } from '@/features/projects/ProjectPicker'
import { useRefresh } from '@/lib/refresh'

/**
 * Base layout: fixed sidebar (project picker) + scrollable main.
 * Themes come from tokens.css — :root is the dark drafting board default;
 * ThemeToggle switches html[data-theme] (the old `dark` class is not a hook).
 */
export function AppShell() {
  return (
    <div className="flex h-screen bg-background text-foreground antialiased">
      <aside
        className="flex w-72 shrink-0 flex-col border-r border-sidebar-border bg-sidebar"
        data-testid="sidebar"
      >
        <header className="flex items-start justify-between gap-2 px-4 py-4">
          <div>
            <h1 className="text-sm font-semibold tracking-widest text-sidebar-foreground">
              AI-CAD
            </h1>
            <p className="mt-0.5 text-xs text-muted-foreground">
              watch the machine think
            </p>
          </div>
          <div className="flex items-center gap-1.5">
            <RefreshButton />
            <ThemeToggle />
          </div>
        </header>
        <Separator className="bg-sidebar-border" />
        <ScrollArea className="min-h-0 flex-1">
          <ProjectPicker />
        </ScrollArea>
        <Separator className="bg-sidebar-border" />
        <footer className="px-4 py-3 text-xs text-muted-foreground">
          read-only view · filesystem is the API
        </footer>
      </aside>
      <main className="min-w-0 flex-1 overflow-auto" data-testid="main">
        <Outlet />
      </main>
    </div>
  )
}

/** Header Refresh — the v1 manual-reload contract (PRD §3.3). Re-fetches all
    surface data in place via the refresh context; no full-page reload. */
function RefreshButton() {
  const { refresh } = useRefresh()
  return (
    <button
      type="button"
      onClick={refresh}
      aria-label="Refresh project data"
      title="Refresh project data"
      className="inline-flex items-center gap-1.5 rounded-sheet border border-stroke-hairline px-2 py-1 text-2xs font-medium tracking-label text-ink-tertiary uppercase transition-colors hover:border-stroke-strong hover:text-ink-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      data-testid="refresh-button"
    >
      <RotateCw className="size-3" aria-hidden />
      refresh
    </button>
  )
}
