import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

/* Identity dot per role — hue IS the identity (tokens.css). Literal class names so
   Tailwind sees them; log names like `cad_designer` normalize to token keys. */
const AGENT_DOT: Record<string, string> = {
  orchestrator: 'bg-agent-orchestrator',
  planner: 'bg-agent-planner',
  'cad-designer': 'bg-agent-cad-designer',
  validator: 'bg-agent-validator',
  repair: 'bg-agent-repair',
  'assembly-resolver': 'bg-agent-assembly-resolver',
  sourcing: 'bg-agent-sourcing',
  reviewer: 'bg-agent-reviewer',
  'dfma-inspector': 'bg-agent-dfma-inspector',
}

interface AgentChipProps extends ComponentProps<'span'> {
  /** Agent name exactly as logged, e.g. "cad_designer". */
  agent: string
}

export function AgentChip({ agent, className, ...props }: AgentChipProps) {
  const key = agent.trim().toLowerCase().replace(/_/g, '-')
  return (
    <span
      data-agent={key}
      className={cn('inline-flex items-center gap-1.5 font-mono text-xs text-ink-secondary', className)}
      {...props}
    >
      <span aria-hidden className={cn('size-2 shrink-0 rounded-full', AGENT_DOT[key] ?? 'bg-ink-faint')} />
      {agent}
    </span>
  )
}
