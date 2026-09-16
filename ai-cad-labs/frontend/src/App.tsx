import { Suspense, lazy } from 'react'
import type { ComponentType } from 'react'
import { Route, Routes } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { NotFound } from '@/components/NotFound'
import { RefreshProvider } from '@/lib/refresh'
import { NoProjectSelected, ProjectDashboard } from '@/features/projects/ProjectDashboard'

/* Sibling build agents are landing PartDetail / AssemblyView in parallel. Glob
   resolves to {} while a file is absent, so its route degrades to ComingSoon
   instead of a build error, and picks the module up as soon as it exists. */
function lazySurface(
  loaders: Record<string, () => Promise<unknown>>,
  exportName: string,
  label: string,
) {
  return lazy(async (): Promise<{ default: ComponentType }> => {
    const load = Object.values(loaders)[0]
    if (!load) return { default: () => <ComingSoon surface={label} /> }
    const mod = (await load()) as Record<string, ComponentType>
    const Component = mod[exportName] ?? mod.default
    return { default: Component ?? (() => <ComingSoon surface={label} />) }
  })
}

const PartDetail = lazySurface(
  import.meta.glob('./features/parts/PartDetail.tsx'),
  'PartDetail',
  'Part detail',
)
const AssemblyView = lazySurface(
  import.meta.glob('./features/assembly/AssemblyView.tsx'),
  'AssemblyView',
  'Assembly',
)

function ComingSoon({ surface }: { surface: string }) {
  return (
    <div className="flex h-full items-center justify-center p-8" data-testid="coming-soon">
      <p className="rounded-md border border-dashed border-stroke-hairline px-4 py-3 text-sm text-ink-tertiary">
        {surface} view is being built — check back shortly.
      </p>
    </div>
  )
}

function RouteLoading() {
  return <p className="p-6 text-sm text-ink-tertiary">Loading…</p>
}

export default function App() {
  return (
    <RefreshProvider>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<NoProjectSelected />} />
          <Route path="projects/:name" element={<ProjectDashboard />} />
          <Route
            path="projects/:name/parts/:part"
            element={
              <Suspense fallback={<RouteLoading />}>
                <PartDetail />
              </Suspense>
            }
          />
          <Route
            path="projects/:name/assembly"
            element={
              <Suspense fallback={<RouteLoading />}>
                <AssemblyView />
              </Suspense>
            }
          />
          <Route
            path="*"
            element={
              <NotFound title="Page not found" detail="That route doesn’t exist." />
            }
          />
        </Route>
      </Routes>
    </RefreshProvider>
  )
}
