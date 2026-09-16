import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { useParams } from 'react-router-dom'
import { NegotiationCard } from '@/components/negotiation/NegotiationCard'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useRefresh } from '@/lib/refresh'
import { loadProject } from '@/lib/model'
import type { ProjectModel } from '@/lib/model'
import { NotFound } from '@/components/NotFound'
import { AssemblySheet } from './AssemblySheet'
import { DfaPanel } from './DfaPanel'
import { LegendChips } from './LegendChips'
import { MarkdownBlock } from './MarkdownBlock'
import { ActivityStrip } from '@/components/activity/ActivityStrip'

/**
 * /projects/:name/assembly — the colored assembly sheet composed with its
 * legend, notes, DFA verdict, and negotiation minutes. loadProject is the sole
 * data path: it returns null for a missing project (manifest 404 → not-found)
 * and carries the manifest-gated raw dfa text (assembly.dfaRaw) for DfaPanel's
 * crash-record inspection — so no separate (ungated) dfa fetch is needed.
 */

type LoadState =
  | { phase: 'loading' }
  | { phase: 'missing' }
  | { phase: 'ready'; model: ProjectModel }

function SectionHeading({ children }: { children: ReactNode }) {
  return <h2 className="text-2xs tracking-label uppercase text-ink-tertiary">{children}</h2>
}

export default function AssemblyView() {
  const { name } = useParams<{ name: string }>()
  const [state, setState] = useState<LoadState>({ phase: 'loading' })
  const { refreshToken } = useRefresh()

  useEffect(() => {
    if (!name) {
      setState({ phase: 'missing' })
      return
    }
    let cancelled = false
    setState({ phase: 'loading' })
    void (async () => {
      const model = await loadProject(name)
      if (cancelled) return
      // null = project does not exist (manifest 404) → not-found, zero probes.
      setState(model ? { phase: 'ready', model } : { phase: 'missing' })
    })()
    return () => {
      cancelled = true
    }
  }, [name, refreshToken])

  if (state.phase === 'loading') {
    return (
      <p className="p-8 text-sm text-ink-tertiary" data-testid="assembly-loading">
        Loading assembly…
      </p>
    )
  }

  if (state.phase === 'missing') {
    return (
      <NotFound
        testid="assembly-missing"
        title={`Project “${name}” not found`}
        detail="No such project in the register."
        home="/"
        homeLabel="project register"
      />
    )
  }

  const { model } = state
  const { assembly, conflicts } = model

  return (
    <div className="flex min-w-0 flex-col gap-8 p-8" data-testid="assembly-view">
      {name ? <ActivityStrip project={name} /> : null}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_16rem]">
        <AssemblySheet project={model.name} renders={assembly.renders} />
        <section className="flex flex-col gap-2">
          <SectionHeading>Color legend</SectionHeading>
          <LegendChips legend={assembly.legend} partNames={model.parts.map((p) => p.name)} />
        </section>
      </div>

      <Tabs defaultValue="notes" data-testid="assembly-doc-tabs">
        <TabsList>
          <TabsTrigger value="notes" data-testid="tab-notes">
            Assembly Notes
          </TabsTrigger>
          <TabsTrigger value="dfa" data-testid="tab-dfa">
            DFA
          </TabsTrigger>
          <TabsTrigger value="negotiations" data-testid="tab-negotiations">
            Negotiations
          </TabsTrigger>
        </TabsList>

        <TabsContent value="notes">
          {assembly.md ? (
            <MarkdownBlock md={assembly.md} />
          ) : (
            <p className="text-sm text-ink-tertiary" data-testid="assembly-md-empty">
              No assembly notes yet.
            </p>
          )}
        </TabsContent>

        <TabsContent value="dfa">
          <DfaPanel report={assembly.dfa} raw={assembly.dfaRaw} />
        </TabsContent>

        <TabsContent value="negotiations">
          {conflicts.length === 0 ? (
            <p className="text-sm text-ink-tertiary" data-testid="negotiations-empty">
              No conflicts negotiated yet — the department is in agreement.
            </p>
          ) : (
            <div className="flex flex-col gap-4">
              {conflicts.map((conflict) => (
                <NegotiationCard key={conflict.id} conflict={conflict} />
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}
