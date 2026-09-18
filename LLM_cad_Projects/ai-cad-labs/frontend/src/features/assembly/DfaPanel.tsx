import type { DfmaFinding, DfmaReport, DfmaSeverity } from '@/lib/parsers/dfma'

/**
 * DFA report panel. Three degraded shapes exist in real runs beyond a full
 * report, and each renders distinctly (never as fake scores):
 *  - file absent            -> quiet pending state
 *  - evaluator crash record -> {"success": false, "error": "<traceback>"}:
 *    parseDfmaReport flattens this to a hollow report, so the RAW text is
 *    inspected here and shown as "DFA failed: <error>"
 *  - partial report         -> counts > 0 but empty results[]: counts shown,
 *    with an explicit "findings not recorded" note
 */

const SEVERITY_CHIP: Record<DfmaSeverity, string> = {
  critical: 'border-fail-line bg-fail-fill text-fail-ink',
  major: 'border-warn-line bg-warn-fill text-warn-ink',
  minor: 'border-note-line bg-note-fill text-note-ink',
}

const SEVERITY_ORDER: DfmaSeverity[] = ['critical', 'major', 'minor']

function errorRecord(raw: string | null): string | null {
  if (!raw) return null
  try {
    const data: unknown = JSON.parse(raw)
    if (typeof data !== 'object' || data === null || Array.isArray(data)) return null
    const rec = data as Record<string, unknown>
    if (typeof rec.error === 'string' && rec.error && !('overall_verdict' in rec)) return rec.error
    return null
  } catch {
    return null
  }
}

function FindingRow({ finding, kind }: { finding: DfmaFinding; kind: 'failure' | 'uncertain' }) {
  const chip = kind === 'uncertain' ? SEVERITY_CHIP.major : SEVERITY_CHIP[finding.severity]
  return (
    <li className="flex flex-col gap-1 border-b border-stroke-hairline py-2.5 last:border-b-0">
      <div className="flex items-center gap-2">
        <span
          className={`rounded-sm border px-1.5 py-px text-2xs tracking-label uppercase ${chip} ${
            kind === 'uncertain' ? 'border-dashed' : ''
          }`}
        >
          {kind === 'uncertain' ? 'uncertain' : finding.severity}
        </span>
        {finding.rule_id && (
          <span className="font-mono text-xs text-foreground">{finding.rule_id}</span>
        )}
      </div>
      {finding.description && (
        <p className="text-sm leading-6 text-foreground">{finding.description}</p>
      )}
      {finding.observation && (
        <p className="text-sm leading-6 text-ink-secondary">{finding.observation}</p>
      )}
      {finding.recommendation && (
        <p className="text-sm leading-6 text-ink-secondary">
          <span className="text-2xs tracking-label uppercase text-ink-tertiary">rec — </span>
          {finding.recommendation}
        </p>
      )}
      {finding.fix_hint && (
        <details className="text-sm">
          <summary className="cursor-pointer text-2xs tracking-label uppercase text-ink-tertiary select-none">
            fix hint
          </summary>
          <p className="mt-1 leading-6 text-ink-secondary">{finding.fix_hint}</p>
        </details>
      )}
    </li>
  )
}

export function DfaPanel({ report, raw }: { report: DfmaReport | null; raw: string | null }) {
  const error = errorRecord(raw)

  if (error) {
    const headline = error.trim().split('\n')[0]
    return (
      <div data-testid="dfa-panel" data-state="error" className="flex flex-col gap-2">
        <p className="text-sm font-medium text-fail-ink">DFA failed: {headline}</p>
        <pre className="max-h-40 overflow-auto rounded-sm border border-fail-line bg-surface-inset p-3 font-mono text-xs leading-5 text-ink-secondary">
          {error.trim()}
        </pre>
      </div>
    )
  }

  if (!report) {
    return (
      <p data-testid="dfa-panel" data-state="pending" className="text-sm text-ink-tertiary">
        No DFA report yet — the inspector hasn't run on this assembly.
      </p>
    )
  }

  const { verdict, counts } = report
  const failures = [...report.failures].sort(
    (a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity),
  )
  const verdictChip =
    verdict === 'pass'
      ? 'border-pass-line bg-pass-fill text-pass-ink'
      : verdict === 'fail'
        ? 'border-fail-line bg-fail-fill text-fail-ink'
        : 'border-stroke-object bg-surface-inset text-ink-secondary'
  const findingsMissing = counts.failed > 0 && failures.length === 0

  return (
    <div data-testid="dfa-panel" data-state={verdict} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span
          data-testid="dfa-verdict"
          className={`rounded-sm border px-2 py-0.5 text-2xs font-medium tracking-label uppercase ${verdictChip}`}
        >
          {verdict}
        </span>
        <dl className="flex gap-4 text-xs tabular-nums">
          {(
            [
              ['evaluated', counts.evaluated, 'text-ink-secondary'],
              ['passed', counts.passed, 'text-pass-ink'],
              ['failed', counts.failed, 'text-fail-ink'],
              ['uncertain', counts.uncertain, 'text-warn-ink'],
            ] as const
          ).map(([label, n, ink]) => (
            <div key={label} className="flex items-baseline gap-1.5">
              <dt className="text-2xs tracking-label uppercase text-ink-tertiary">{label}</dt>
              <dd className={`font-medium ${ink}`}>{n}</dd>
            </div>
          ))}
        </dl>
      </div>
      {findingsMissing && (
        <p className="text-sm text-ink-tertiary" data-testid="dfa-findings-missing">
          {counts.failed} rule{counts.failed === 1 ? '' : 's'} failed — detailed findings were not
          recorded in this report.
        </p>
      )}
      {(failures.length > 0 || report.warnings.length > 0) && (
        <ul className="flex flex-col" data-testid="dfa-findings">
          {failures.map((f, i) => (
            <FindingRow key={`f-${f.rule_id}-${i}`} finding={f} kind="failure" />
          ))}
          {report.warnings.map((w, i) => (
            <FindingRow key={`w-${w.rule_id}-${i}`} finding={w} kind="uncertain" />
          ))}
        </ul>
      )}
    </div>
  )
}
