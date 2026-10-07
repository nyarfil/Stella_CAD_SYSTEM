import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import { RevisionLog } from '@/components/RevisionLog'
import { StatusChip } from '@/components/StatusChip'
import type { StatusTone } from '@/components/StatusChip'
import { TitleBlock } from '@/components/TitleBlock'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { projectFileUrl } from '@/lib/api'
import { useRefresh } from '@/lib/refresh'
import { loadProject } from '@/lib/model'
import type { PartModel, ProjectModel } from '@/lib/model'
import { NotFound } from '@/components/NotFound'
import type { ParsedBom } from '@/lib/parsers/bom'
import type { PlanPart } from '@/lib/parsers/designPlan'
import type { ValidationStatus } from '@/lib/parsers/notes'
import { cn } from '@/lib/utils'
import { ActivityStrip } from '@/components/activity/ActivityStrip'

type State =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'missing' }
  | { status: 'ready'; project: ProjectModel }

const VERDICT: Record<ValidationStatus, { tone: StatusTone; label: string }> = {
  passed: { tone: 'pass', label: 'Passed' },
  failed: { tone: 'fail', label: 'Failed' },
  pending: { tone: 'neutral', label: 'Pending' },
}

export function ProjectDashboard() {
  const { name } = useParams<{ name: string }>()
  const [state, setState] = useState<State>({ status: 'loading' })
  const { refreshToken } = useRefresh()

  useEffect(() => {
    if (!name) return
    let cancelled = false
    setState({ status: 'loading' })
    loadProject(name)
      .then((project) => {
        if (cancelled) return
        // null = the project does not exist (manifest 404) — route to NotFound
        // instead of rendering an empty dashboard (and without probing).
        setState(project ? { status: 'ready', project } : { status: 'missing' })
      })
      .catch((err: Error) => {
        if (!cancelled) setState({ status: 'error', message: err.message })
      })
    return () => {
      cancelled = true
    }
  }, [name, refreshToken])

  if (!name) return <NoProjectSelected />

  if (state.status === 'loading') {
    return (
      <div className="space-y-6 p-6" data-testid="dashboard-loading">
        <Skeleton className="h-20 w-full" />
        <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-3">
          <Skeleton className="h-56" />
          <Skeleton className="h-56" />
          <Skeleton className="h-56" />
          <Skeleton className="h-56" />
        </div>
      </div>
    )
  }

  if (state.status === 'missing') {
    return (
      <NotFound
        title={`Project “${name}” not found`}
        detail="No such project in the register."
        home="/"
        homeLabel="project register"
      />
    )
  }

  if (state.status === 'error') {
    return (
      <p className="p-6 text-sm text-destructive" data-testid="dashboard-error">
        Could not load project {name}: {state.message}
      </p>
    )
  }

  const { project } = state
  const partByName = new Map(project.parts.map((part) => [part.name, part]))
  const counts = { passed: 0, failed: 0, pending: 0 }
  for (const part of project.parts) counts[part.validation] += 1
  const openConflicts = project.conflicts.filter((c) => c.status === 'open').length
  const resolvedConflicts = project.conflicts.length - openConflicts
  const buyCount = project.designPlan.parts.filter((p) => p.kind === 'buy').length

  return (
    <div className="space-y-6 p-6" data-testid="project-dashboard">
      <TitleBlock
        title={project.name}
        fields={[
          {
            label: 'Parts',
            value: buyCount > 0 ? `${project.parts.length} make · ${buyCount} buy` : String(project.parts.length),
          },
          { label: 'Revs', value: String(project.logEntries.length).padStart(3, '0') },
          { label: 'Conflicts', value: `${openConflicts} open` },
        ]}
        stamps={
          <>
            {counts.failed > 0 && <StatusChip tone="fail">{counts.failed} failed</StatusChip>}
            {counts.passed > 0 && <StatusChip tone="pass">{counts.passed} passed</StatusChip>}
            {counts.pending > 0 && <StatusChip tone="neutral">{counts.pending} pending</StatusChip>}
          </>
        }
      />

      {name ? <ActivityStrip project={name} /> : null}
      <Link
        to={`/projects/${encodeURIComponent(project.name)}/assembly`}
        className="flex flex-wrap items-center gap-2 rounded-sheet border border-stroke-object bg-card px-4 py-2.5 transition-colors hover:border-stroke-strong hover:bg-wash-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        data-testid="assembly-entry"
      >
        <span className="text-2xs font-medium tracking-label text-ink-tertiary uppercase">Assembly</span>
        {project.conflicts.filter((c) => c.status === 'open').length > 0 ? (
          <StatusChip tone="fail">
            {project.conflicts.filter((c) => c.status === 'open').length} conflicts open
          </StatusChip>
        ) : project.conflicts.length > 0 ? (
          <StatusChip tone="pass">conflicts resolved</StatusChip>
        ) : null}
        <span className="ml-auto text-xs text-ink-tertiary">open assembly view →</span>
      </Link>
      <section className="space-y-2" aria-label="Parts">
        <SectionLabel>Parts — design_plan.md build order</SectionLabel>
        {project.designPlan.parts.length === 0 ? (
          <EmptyNote>design_plan.md not written yet — parts appear once the planner runs.</EmptyNote>
        ) : (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-3" data-testid="parts-grid">
            {project.designPlan.parts.map((plan) => (
              <PartCard key={plan.name} project={project.name} plan={plan} part={partByName.get(plan.name)} />
            ))}
          </div>
        )}
      </section>

      <Tabs defaultValue="goals" data-testid="dashboard-doc-tabs">
        <TabsList>
          <TabsTrigger value="goals" data-testid="tab-goals">
            Goals
          </TabsTrigger>
          <TabsTrigger value="design-plan" data-testid="tab-design-plan">
            Design Plan
          </TabsTrigger>
          <TabsTrigger value="bom" data-testid="tab-bom">
            BOM
          </TabsTrigger>
          <TabsTrigger value="revision-log" data-testid="tab-revision-log">
            Revision Log
          </TabsTrigger>
          <TabsTrigger value="conflicts" data-testid="tab-conflicts">
            Conflicts
          </TabsTrigger>
        </TabsList>

        <TabsContent value="goals">
          <section className="space-y-2" aria-label="Goals">
            <SectionLabel>Goals — goals.md</SectionLabel>
            <div className="rounded-sheet border border-stroke-object bg-card p-4">
              {project.goalsMd ? (
                <Markdown>{project.goalsMd}</Markdown>
              ) : (
                <EmptyNote>goals.md not written yet.</EmptyNote>
              )}
            </div>
          </section>
        </TabsContent>

        <TabsContent value="design-plan">
          <section className="space-y-2" aria-label="Design plan">
            <SectionLabel>Design plan — design_plan.md</SectionLabel>
            {project.designPlan.raw.trim() ? (
              <div className="rounded-sheet border border-stroke-object bg-card p-4">
                <Markdown>{project.designPlan.raw}</Markdown>
              </div>
            ) : (
              <EmptyNote>design_plan.md not written yet.</EmptyNote>
            )}
          </section>
        </TabsContent>

        <TabsContent value="bom">
          <section className="space-y-2" aria-label="Bill of materials">
            <SectionLabel>BOM — external/bom.md</SectionLabel>
            <BomTable bom={project.bom} />
          </section>
        </TabsContent>

        <TabsContent value="revision-log">
          <section className="space-y-2" aria-label="Revision log">
            <SectionLabel>Revision log — design_log.md</SectionLabel>
            <RevisionLog entries={project.logEntries} />
          </section>
        </TabsContent>

        <TabsContent value="conflicts">
          {project.conflicts.length > 0 ? (
            <Link
              to={`/projects/${encodeURIComponent(project.name)}/assembly`}
              className="flex flex-wrap items-center gap-2 rounded-sheet border border-stroke-object bg-card px-4 py-2.5 transition-colors hover:border-stroke-strong hover:bg-wash-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
              data-testid="conflicts-strip"
            >
              <span className="text-2xs font-medium tracking-label text-ink-tertiary uppercase">Conflicts</span>
              {openConflicts > 0 ? (
                <StatusChip tone="fail">{openConflicts} open</StatusChip>
              ) : (
                <StatusChip tone="pass">all resolved</StatusChip>
              )}
              {openConflicts > 0 && resolvedConflicts > 0 && (
                <StatusChip tone="pass">{resolvedConflicts} resolved</StatusChip>
              )}
              <span className="ml-auto text-xs text-ink-tertiary">assembly →</span>
            </Link>
          ) : (
            <EmptyNote>No conflicts recorded yet.</EmptyNote>
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}

export function NoProjectSelected() {
  return (
    <div className="flex h-full items-center justify-center" data-testid="dashboard-empty">
      <p className="text-sm text-muted-foreground">
        Select a project to watch the machine think.
      </p>
    </div>
  )
}

/* ── parts grid ─────────────────────────────────────────────────────────── */

function PartCard({ project, plan, part }: { project: string; plan: PlanPart; part?: PartModel }) {
  const balloon = (
    <span
      aria-label={`Build order ${plan.index}`}
      className="flex size-6 shrink-0 items-center justify-center rounded-full border border-stroke-strong font-mono text-xs tabular-nums"
    >
      {plan.index}
    </span>
  )

  // Buy parts have no directory under assembly/ — a card with no artifacts to link.
  if (!part) {
    return (
      <div
        className="flex items-start gap-3 rounded-sheet border border-dashed border-stroke-hairline bg-card p-3"
        data-testid={`part-card-${plan.name}`}
      >
        {balloon}
        <div className="min-w-0 flex-1 space-y-1.5">
          <p className="truncate font-mono text-sm text-ink-secondary" title={plan.name}>
            {plan.name}
          </p>
          <div className="flex flex-wrap gap-1">
            <StatusChip variant="tag" presence="absent">buy</StatusChip>
            {plan.qty != null && (
              <StatusChip variant="tag" presence="pending">qty {plan.qty}</StatusChip>
            )}
          </div>
          <p className="text-xs text-ink-tertiary">Sourced component — see BOM.</p>
        </div>
      </div>
    )
  }

  const verdict = VERDICT[part.validation]
  return (
    <Link
      to={`/projects/${encodeURIComponent(project)}/parts/${encodeURIComponent(part.name)}`}
      className="block rounded-sheet border border-stroke-object bg-card p-3 transition-colors hover:border-stroke-strong hover:bg-wash-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      data-testid={`part-card-${part.name}`}
    >
      <div className="flex items-center gap-3">
        {balloon}
        <p className="min-w-0 flex-1 truncate font-mono text-sm font-medium" title={part.name}>
          {part.name}
        </p>
      </div>
      <div className="mt-2">
        <PartThumb project={project} part={part} />
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        <StatusChip tone={verdict.tone}>{verdict.label}</StatusChip>
        {part.proposalPending && <StatusChip tone="warn">proposal</StatusChip>}
        <StatusChip variant="tag" presence={part.hasCode ? 'present' : 'absent'}>code</StatusChip>
        <StatusChip variant="tag" presence={part.hasRenders ? 'present' : 'absent'}>renders</StatusChip>
      </div>
    </Link>
  )
}

/** iso_clean.png on paper (bg-sheet is theme-invariant white, like the PNGs). */
function PartThumb({ project, part }: { project: string; part: PartModel }) {
  const [failed, setFailed] = useState(false)
  const showImg = part.hasRenders && !failed
  return (
    <div className="flex aspect-[4/3] items-center justify-center overflow-hidden rounded-sm border border-stroke-hairline bg-sheet">
      {showImg ? (
        <img
          src={projectFileUrl(project, `assembly/${part.name}/renders/iso_clean.png`)}
          alt={`${part.name} isometric render`}
          loading="lazy"
          className="h-full w-full object-contain"
          onError={() => setFailed(true)}
        />
      ) : (
        <span className="text-2xs tracking-label text-sheet-ink-soft uppercase">No render yet</span>
      )}
    </div>
  )
}

/** BOM as a parts-list table when rows parsed; raw markdown as the fallback. */
function BomTable({ bom }: { bom: ParsedBom }) {
  if (bom.rows.length === 0) {
    return bom.raw.trim() ? (
      <div className="rounded-sheet border border-stroke-object bg-card p-4">
        <Markdown>{bom.raw}</Markdown>
      </div>
    ) : (
      <EmptyNote>external/bom.md not written yet — the sourcing agent produces it.</EmptyNote>
    )
  }
  return (
    <div className="overflow-hidden rounded-md border border-stroke-object" data-testid="bom-table">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-stroke-strong">
            {['Qty', 'Part', 'Specification', 'Source', 'Notes'].map((label) => (
              <th
                key={label}
                className="px-3 py-1.5 text-left text-2xs font-medium tracking-label text-ink-tertiary uppercase"
              >
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {bom.rows.map((row, i) => (
            <tr key={i} className="border-b border-stroke-hairline align-top last:border-0 hover:bg-wash-hover">
              <td className="w-12 px-3 py-1.5 font-mono text-xs text-ink-tertiary tabular-nums">{row.qty ?? '—'}</td>
              <td className="px-3 py-1.5 font-mono text-xs">{row.part}</td>
              <td className="px-3 py-1.5 text-ink-secondary">{row.specification}</td>
              <td className="px-3 py-1.5 text-ink-secondary">{row.source}</td>
              <td className="px-3 py-1.5 text-ink-tertiary">{row.notes}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ── shared bits ────────────────────────────────────────────────────────── */

function SectionLabel({ children }: { children: ReactNode }) {
  return <h3 className="text-2xs font-medium tracking-label text-ink-tertiary uppercase">{children}</h3>
}

function EmptyNote({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-md border border-dashed border-stroke-hairline px-3 py-2 text-sm text-ink-tertiary">
      {children}
    </p>
  )
}

/** Markdown on the drafting board — token-mapped elements, no typography plugin. */
function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown
      components={{
        h1: ({ node, ...props }) => (
          <h1 className="mt-4 mb-1.5 text-base font-semibold first:mt-0" {...props} />
        ),
        h2: ({ node, ...props }) => (
          <h2 className="mt-4 mb-1.5 text-sm font-semibold first:mt-0" {...props} />
        ),
        h3: ({ node, ...props }) => (
          <h3 className="mt-3 mb-1 text-sm font-medium first:mt-0" {...props} />
        ),
        p: ({ node, ...props }) => (
          <p className="my-1.5 text-sm leading-relaxed text-ink-secondary first:mt-0 last:mb-0" {...props} />
        ),
        ul: ({ node, ...props }) => (
          <ul className="my-1.5 list-disc space-y-1 pl-5 text-sm text-ink-secondary" {...props} />
        ),
        ol: ({ node, ...props }) => (
          <ol className="my-1.5 list-decimal space-y-1 pl-5 text-sm text-ink-secondary" {...props} />
        ),
        a: ({ node, ...props }) => (
          <a className="text-foreground underline decoration-stroke-strong underline-offset-2" {...props} />
        ),
        strong: ({ node, ...props }) => <strong className="font-semibold text-foreground" {...props} />,
        code: ({ node, className, ...props }) => (
          <code className={cn('rounded-sm bg-surface-inset px-1 py-px font-mono text-[0.85em]', className)} {...props} />
        ),
        pre: ({ node, ...props }) => (
          <pre
            className="my-2 overflow-x-auto rounded-md border border-stroke-hairline bg-surface-inset p-3 font-mono text-xs leading-relaxed"
            {...props}
          />
        ),
        blockquote: ({ node, ...props }) => (
          <blockquote className="my-1.5 border-l-2 border-stroke-strong pl-3 text-ink-tertiary" {...props} />
        ),
        table: ({ node, ...props }) => <table className="my-2 w-full border-collapse text-sm" {...props} />,
        th: ({ node, ...props }) => (
          <th
            className="border-b border-stroke-strong px-2 py-1 text-left text-2xs font-medium tracking-label text-ink-tertiary uppercase"
            {...props}
          />
        ),
        td: ({ node, ...props }) => (
          <td className="border-b border-stroke-hairline px-2 py-1 align-top text-ink-secondary" {...props} />
        ),
        hr: ({ node, ...props }) => <hr className="my-3 border-stroke-hairline" {...props} />,
      }}
    >
      {children}
    </ReactMarkdown>
  )
}
