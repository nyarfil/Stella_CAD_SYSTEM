/**
 * dfma_report.json (per part, --mode=dfm) and dfa_report.json (assembly,
 * --mode=dfa) from tools.dfma_evaluator. Reports are frequently ABSENT in
 * real runs (evaluator crashes: missing API key, token-limit failures) and
 * may be partial (a dfa_report.json with overall_verdict but empty results[]).
 * Everything here is null-safe; callers treat null as "no report produced".
 */

export type DfmaSeverity = 'critical' | 'major' | 'minor'

export interface DfmaFinding {
  rule_id: string
  severity: DfmaSeverity
  description: string
  observation: string
  recommendation: string
  fix_hint?: string
}

export interface DfmaCounts {
  evaluated: number
  passed: number
  failed: number
  uncertain: number
}

export interface DfmaReport {
  /** 'pass' | 'fail' as emitted by the evaluator (kept open for new verdicts). */
  verdict: string
  /** 'dfm' (part) or 'dfa' (assembly). */
  evalType: string
  counts: DfmaCounts
  /** results[] entries with verdict=fail. */
  failures: DfmaFinding[]
  /** results[] entries with verdict=uncertain (vision could not confirm). */
  warnings: DfmaFinding[]
}

const SEVERITIES: readonly string[] = ['critical', 'major', 'minor']

function toFinding(raw: Record<string, unknown>): DfmaFinding {
  const str = (k: string) => (typeof raw[k] === 'string' ? (raw[k] as string) : '')
  const severity = SEVERITIES.includes(str('severity')) ? (str('severity') as DfmaSeverity) : 'minor'
  const finding: DfmaFinding = {
    rule_id: str('rule_id'),
    severity,
    description: str('rule_description') || str('description'),
    observation: str('observation'),
    recommendation: str('recommendation'),
  }
  if (typeof raw.fix_hint === 'string') finding.fix_hint = raw.fix_hint
  return finding
}

/** Accepts raw JSON text or an already-parsed object; null when absent/unreadable. */
export function parseDfmaReport(raw: string | object | null | undefined): DfmaReport | null {
  if (raw == null) return null
  let data: unknown = raw
  if (typeof raw === 'string') {
    if (!raw.trim()) return null
    try {
      data = JSON.parse(raw)
    } catch {
      return null
    }
  }
  if (typeof data !== 'object' || data === null || Array.isArray(data)) return null
  const rec = data as Record<string, unknown>
  const results = Array.isArray(rec.results)
    ? (rec.results.filter((r) => typeof r === 'object' && r !== null) as Record<string, unknown>[])
    : []
  const num = (k: string, fallback: number) =>
    typeof rec[k] === 'number' ? (rec[k] as number) : fallback
  const byVerdict = (v: string) => results.filter((r) => r.verdict === v)
  return {
    verdict: typeof rec.overall_verdict === 'string' ? rec.overall_verdict : 'unknown',
    evalType: typeof rec.eval_type === 'string' ? rec.eval_type : '',
    counts: {
      evaluated: num('rules_evaluated', results.length),
      passed: num('rules_passed', byVerdict('pass').length),
      failed: num('rules_failed', byVerdict('fail').length),
      uncertain: num('rules_uncertain', byVerdict('uncertain').length),
    },
    failures: byVerdict('fail').map(toFinding),
    warnings: byVerdict('uncertain').map(toFinding),
  }
}
