import { useEffect, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import { cn } from '@/lib/utils'
import { projectFileUrl } from '@/lib/api'
import { useRefresh } from '@/lib/refresh'
import { loadSinglePart, type PartModel } from '@/lib/model'
import { CodeBlock } from '@/components/code/CodeBlock'
import { NotFound } from '@/components/NotFound'
import type { AttemptLogEntry } from '@/lib/parsers/attemptLog'
import type { DfmaFinding, DfmaSeverity } from '@/lib/parsers/dfma'
import { StatusChip, type StatusTone } from '@/components/StatusChip'
import { RenderSheet } from '@/components/sheet/RenderSheet'
import { VerdictStamp } from '@/components/sheet/VerdictStamp'
import { ScoreBadge } from '@/components/sheet/ScoreBadge'
import './partdetail.css'

type LoadState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; part: PartModel | null }

export default function PartDetail() {
  const { name = '', part: partName = '' } = useParams()
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  const { refreshToken } = useRefresh()

  useEffect(() => {
    let alive = true
    setState({ status: 'loading' })
    // Single-part load — the sheet needs only this part, and this avoids firing
    // every other part's file probes (QA §5 item 7). null = part not found.
    loadSinglePart(name, partName)
      .then((part) => {
        if (alive) setState({ status: 'ready', part })
      })
      .catch((e: unknown) => {
        if (alive)
          setState({ status: 'error', message: e instanceof Error ? e.message : String(e) })
      })
    return () => {
      alive = false
    }
  }, [name, partName, refreshToken])

  if (state.status === 'loading') {
    return <p className="text-sm text-ink-tertiary">Loading part…</p>
  }
  if (state.status === 'error') {
    return <p className="text-sm text-fail-ink">Failed to load project: {state.message}</p>
  }
  const part = state.part
  if (!part) {
    return (
      <NotFound
        title={`Part “${partName}” not found`}
        detail={`No such part in ${name}.`}
        home={`/projects/${name}`}
        homeLabel={name}
      />
    )
  }

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end gap-3">
        <div>
          <div className="font-mono text-2xs uppercase tracking-label text-ink-tertiary">
            <Link to={`/projects/${name}`} className="hover:text-ink-secondary">
              {name}
            </Link>{' '}
            / part
          </div>
          <h1 className="text-xl font-semibold text-foreground">{part.name}</h1>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <StatusChip variant="tag" presence={part.hasCode ? 'present' : 'absent'}>
            code
          </StatusChip>
          <StatusChip variant="tag" presence={part.hasRenders ? 'present' : 'absent'}>
            renders
          </StatusChip>
          {part.proposalPending && <StatusChip tone="warn">proposal pending</StatusChip>}
          <VerdictStamp verdict={part.validation} />
        </div>
      </header>

      <RenderSheet project={name} part={part.name} />

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Constraints">
          <MdBody text={part.constraintsMd} emptyLabel="No constraints.md" />
        </Panel>
        <Panel title="Notes">
          <MdBody text={part.notesMd} emptyLabel="No notes.md" />
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <Panel title="DFMA report">
          {part.dfma ? (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-3">
                <VerdictStamp verdict={part.dfma.verdict} />
                <span className="font-mono text-2xs uppercase tracking-label text-ink-tertiary">
                  {part.dfma.evalType}
                </span>
                <ScoreBadge counts={part.dfma.counts} className="ml-auto" />
              </div>
              <FindingsTable label="Failures" rows={part.dfma.failures} />
              <FindingsTable label="Warnings" rows={part.dfma.warnings} />
              {part.dfma.failures.length === 0 && part.dfma.warnings.length === 0 && (
                <Empty>No failures or warnings.</Empty>
              )}
            </div>
          ) : (
            <Empty>No DFMA report</Empty>
          )}
        </Panel>
        <Panel title="Attempt log">
          <AttemptTimeline entries={part.attempts} />
        </Panel>
      </div>

      {part.hasCode && <CodePanel project={name} part={part.name} />}
    </div>
  )
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-md border bg-card p-3">
      <h2 className="mb-2 font-mono text-2xs uppercase tracking-label text-ink-tertiary">
        {title}
      </h2>
      {children}
    </section>
  )
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="text-sm text-ink-faint">{children}</p>
}

function MdBody({ text, emptyLabel }: { text: string | null; emptyLabel: string }) {
  if (!text) return <Empty>{emptyLabel}</Empty>
  return (
    <div className="md-body text-sm text-ink-secondary">
      <ReactMarkdown>{text}</ReactMarkdown>
    </div>
  )
}

/* part.py viewer — fetched directly (the model tracks only existence); line-
   numbered mono with a copy button, matching the drafting-instrument register. */
function CodePanel({ project, part }: { project: string; part: string }) {
  const [code, setCode] = useState<string | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    let alive = true
    setStatus('loading')
    setCode(null)
    fetch(projectFileUrl(project, `assembly/${part}/part.py`))
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
      .then((t) => {
        if (alive) {
          setCode(t)
          setStatus('ready')
        }
      })
      .catch(() => {
        if (alive) setStatus('error')
      })
    return () => {
      alive = false
    }
  }, [project, part])

  const copy = () => {
    if (!code) return
    void navigator.clipboard?.writeText(code).then(
      () => {
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      },
      () => {},
    )
  }

  return (
    <section className="rounded-md border bg-card p-3" data-testid="code-panel">
      <div className="mb-2 flex items-center gap-2">
        <h2 className="font-mono text-2xs uppercase tracking-label text-ink-tertiary">part.py</h2>
        {status === 'ready' && (
          <button
            type="button"
            onClick={copy}
            className="ml-auto rounded-sm border border-stroke-object px-2 py-0.5 font-mono text-2xs uppercase tracking-label text-ink-tertiary transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            data-testid="code-copy"
          >
            {copied ? 'copied' : 'copy'}
          </button>
        )}
      </div>
      {status === 'loading' && <Empty>Loading code…</Empty>}
      {status === 'error' && <Empty>No part.py</Empty>}
      {status === 'ready' && code && <CodeBlock code={code} />}
    </section>
  )
}

/* Severity → status ink (system.md): critical=fail, major=warn, minor=note. */
const SEV_TONE: Record<DfmaSeverity, StatusTone> = {
  critical: 'fail',
  major: 'warn',
  minor: 'note',
}

/* Findings render severity-first (critical → major → minor) — brief §3; the
   dfma_report.json results[] are unsorted, so the sheet does the ordering. */
const SEV_RANK: Record<DfmaSeverity, number> = { critical: 0, major: 1, minor: 2 }

function FindingsTable({ label, rows }: { label: string; rows: DfmaFinding[] }) {
  if (rows.length === 0) return null
  const sorted = [...rows].sort((a, b) => SEV_RANK[a.severity] - SEV_RANK[b.severity])
  return (
    <div>
      <div className="mb-1 font-mono text-2xs uppercase tracking-label text-ink-tertiary">
        {label} · {rows.length}
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-stroke-object text-left font-mono text-2xs uppercase tracking-label text-ink-tertiary">
            <th className="py-1 pr-2 font-normal">Rule</th>
            <th className="py-1 pr-2 font-normal">Severity</th>
            <th className="py-1 pr-2 font-normal">Finding</th>
            <th className="py-1 font-normal">Fix hint</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((f, i) => (
            <tr key={`${f.rule_id}-${i}`} className="border-b border-stroke-hairline align-top">
              <td className="whitespace-nowrap py-1.5 pr-2 font-mono text-xs text-ink-secondary">
                {f.rule_id}
              </td>
              <td className="py-1.5 pr-2">
                <StatusChip tone={SEV_TONE[f.severity]}>{f.severity}</StatusChip>
              </td>
              <td className="py-1.5 pr-2">
                <div className="text-foreground">{f.description}</div>
                {f.observation && <div className="text-xs text-ink-tertiary">{f.observation}</div>}
              </td>
              <td className="py-1.5 text-xs text-ink-secondary">
                {f.fix_hint ?? f.recommendation}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function outcomeTone(outcome: string): StatusTone {
  const o = outcome.toLowerCase()
  if (/pass|success|approv|promot|resolv/.test(o)) return 'pass'
  if (/fail|reject|error/.test(o)) return 'fail'
  return 'neutral'
}

function AttemptTimeline({ entries }: { entries: AttemptLogEntry[] }) {
  if (entries.length === 0) return <Empty>No attempts logged</Empty>
  return (
    <ol className="max-h-96 space-y-0 overflow-y-auto pr-1">
      {entries.map((e, i) => (
        <li key={i} className="relative border-l border-stroke-object pb-3 pl-4 last:pb-0">
          <span
            className={cn(
              'absolute -left-[3.5px] top-1.5 h-1.5 w-1.5 rounded-full',
              e.outcome && outcomeTone(e.outcome) === 'pass' && 'bg-pass-line',
              e.outcome && outcomeTone(e.outcome) === 'fail' && 'bg-fail-line',
              (!e.outcome || outcomeTone(e.outcome) === 'neutral') && 'bg-stroke-strong',
            )}
          />
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span className="font-mono text-2xs tabular-nums text-ink-tertiary">{e.ts ?? '—'}</span>
            <span className="font-mono text-2xs uppercase tracking-label text-ink-secondary">
              {e.role ?? '?'}
            </span>
            {e.outcome && <StatusChip tone={outcomeTone(e.outcome)}>{e.outcome}</StatusChip>}
          </div>
        </li>
      ))}
    </ol>
  )
}
