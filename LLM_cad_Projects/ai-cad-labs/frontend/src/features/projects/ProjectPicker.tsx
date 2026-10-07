import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { fetchProjects, relativeTime, type ProjectSummary } from '@/lib/api'
import { useRefresh } from '@/lib/refresh'
import { cn } from '@/lib/utils'

type State =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; projects: ProjectSummary[] }

export function ProjectPicker() {
  const [state, setState] = useState<State>({ status: 'loading' })
  const { refreshToken } = useRefresh()

  useEffect(() => {
    fetchProjects()
      .then((projects) => setState({ status: 'ready', projects }))
      .catch((err: Error) => setState({ status: 'error', message: err.message }))
  }, [refreshToken])

  if (state.status === 'loading') {
    return (
      <div className="space-y-2 p-3" data-testid="project-picker-loading">
        <Skeleton className="h-14 w-full" />
        <Skeleton className="h-14 w-full" />
      </div>
    )
  }

  if (state.status === 'error') {
    return (
      <p className="p-4 text-sm text-destructive" data-testid="project-picker-error">
        Could not list projects: {state.message}
      </p>
    )
  }

  if (state.projects.length === 0) {
    return (
      <p className="p-4 text-sm text-muted-foreground" data-testid="project-picker-empty">
        No projects yet — run the harness to create one.
      </p>
    )
  }

  return (
    <nav aria-label="Projects" data-testid="project-picker">
      <ul className="space-y-1 p-2">
        {state.projects.map((project) => (
          <li key={project.name}>
            <NavLink
              to={`/projects/${encodeURIComponent(project.name)}`}
              data-testid={`project-link-${project.name}`}
              className={({ isActive }) =>
                cn(
                  'block rounded-md px-3 py-2 transition-colors hover:bg-sidebar-accent',
                  isActive && 'bg-sidebar-accent',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
                )
              }
            >
              <span className="flex items-center justify-between gap-2">
                <span className="truncate font-medium text-sidebar-foreground">
                  {project.name}
                </span>
                <Badge variant="secondary" className="shrink-0 tabular-nums">
                  {project.partCount} {project.partCount === 1 ? 'part' : 'parts'}
                </Badge>
              </span>
              <span className="mt-0.5 block text-xs text-muted-foreground">
                updated {relativeTime(project.lastModified)}
              </span>
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}
