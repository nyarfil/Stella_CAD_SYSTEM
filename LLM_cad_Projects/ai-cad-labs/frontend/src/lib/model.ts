/**
 * loadProject() — assembles the full typed model for one project by pulling
 * raw artifacts through the read-only projects API and feeding each through
 * its parser. Missing or unreadable optional artifacts become nulls / empty
 * collections; loadProject never throws on partial project state.
 *
 * There is no directory-listing endpoint (the filesystem API serves only
 * /api/projects plus raw files), so the part inventory is derived from the
 * design plan and per-part artifacts are probed at their conventional paths.
 */
import { fetchManifest, projectFileUrl } from './api'
import { parseAttemptLog } from './parsers/attemptLog'
import type { AttemptLogEntry } from './parsers/attemptLog'
import { parseBom } from './parsers/bom'
import type { ParsedBom } from './parsers/bom'
import { parseConflicts } from './parsers/conflicts'
import type { Conflict } from './parsers/conflicts'
import { parseDesignLog } from './parsers/designLog'
import type { DesignLogEntry } from './parsers/designLog'
import { parseDesignPlan } from './parsers/designPlan'
import type { ParsedDesignPlan } from './parsers/designPlan'
import { parseDfmaReport } from './parsers/dfma'
import type { DfmaReport } from './parsers/dfma'
import { parseNotes } from './parsers/notes'
import type { ValidationStatus } from './parsers/notes'
import { parseColorLegend, parseRenderFilenames, STANDARD_RENDER_FILENAMES } from './parsers/renders'
import type { LegendEntry, RenderSet } from './parsers/renders'

export interface PartModel {
  name: string
  constraintsMd: string | null
  notesMd: string | null
  validation: ValidationStatus
  dfma: DfmaReport | null
  attempts: AttemptLogEntry[]
  renders: RenderSet
  hasCode: boolean
  hasRenders: boolean
  proposalPending: boolean
}

export interface AssemblyModel {
  md: string | null
  dfa: DfmaReport | null
  /** Raw dfa_report.json text (manifest-gated) — DfaPanel inspects it for
      evaluator crash records that parseDfmaReport flattens away. Null when the
      report is absent, so the assembly view needs no separate (ungated) fetch. */
  dfaRaw: string | null
  renders: RenderSet
  legend: LegendEntry[]
}

export interface ProjectModel {
  name: string
  goalsMd: string | null
  designPlan: ParsedDesignPlan
  bom: ParsedBom
  conflicts: Conflict[]
  logEntries: DesignLogEntry[]
  parts: PartModel[]
  assembly: AssemblyModel
}

async function fetchText(project: string, rel: string): Promise<string | null> {
  try {
    const res = await fetch(projectFileUrl(project, rel))
    return res.ok ? await res.text() : null
  } catch {
    return null
  }
}

async function fileExists(project: string, rel: string): Promise<boolean> {
  try {
    const res = await fetch(projectFileUrl(project, rel))
    void res.body?.cancel().catch(() => {})
    return res.ok
  } catch {
    return false
  }
}

/** The renderer always emits the fixed 8 standard views, so URLs are deterministic. */
function renderSet(project: string, rendersDir: string): RenderSet {
  return parseRenderFilenames(STANDARD_RENDER_FILENAMES, (filename) =>
    projectFileUrl(project, `${rendersDir}/${filename}`),
  )
}

/**
 * `present` = this part's file-existence map from the project manifest. When
 * supplied, we fetch ONLY files known to exist (no 404 probes); when null (the
 * manifest endpoint was unavailable), we fall back to probing every path.
 */
async function loadPart(
  project: string,
  name: string,
  present: Record<string, boolean> | null,
): Promise<PartModel> {
  const dir = `assembly/${name}`
  const want = (key: string) => (present ? present[key] === true : true)

  const [constraintsMd, notesMd, dfmaText, attemptText] = await Promise.all([
    want('constraints.md') ? fetchText(project, `${dir}/constraints.md`) : Promise.resolve(null),
    want('notes.md') ? fetchText(project, `${dir}/notes.md`) : Promise.resolve(null),
    want('dfma_report.json') ? fetchText(project, `${dir}/dfma_report.json`) : Promise.resolve(null),
    want('attempt_log.json') ? fetchText(project, `${dir}/attempt_log.json`) : Promise.resolve(null),
  ])

  const [hasCode, proposalPending, hasRenders] = present
    ? [present['part.py'] === true, present['part.proposal.py'] === true, present['renders'] === true]
    : await Promise.all([
        fileExists(project, `${dir}/part.py`),
        fileExists(project, `${dir}/part.proposal.py`),
        fileExists(project, `${dir}/renders/${STANDARD_RENDER_FILENAMES[0]}`),
      ])

  return {
    name,
    constraintsMd,
    notesMd,
    validation: parseNotes(notesMd).validation,
    dfma: parseDfmaReport(dfmaText),
    attempts: parseAttemptLog(attemptText),
    renders: hasRenders ? renderSet(project, `${dir}/renders`) : [],
    hasCode,
    hasRenders,
    proposalPending,
  }
}

export async function loadProject(name: string): Promise<ProjectModel | null> {
  // One manifest walk gates every fetch below — absent optional files are never
  // requested (no console 404s). If the endpoint is unavailable, manifest is
  // null and we fall back to unconditional fetches (the pre-manifest behavior).
  const manifest = await fetchManifest(name)
  // 404 = the project does not exist → return null WITHOUT probing (probing a
  // missing project fired ~24 console 404s + rendered an empty dashboard).
  if (manifest === 'missing') return null
  const wantTop = (key: string) => (manifest ? manifest.files[key] === true : true)
  const gated = (key: string, rel: string) =>
    wantTop(key) ? fetchText(name, rel) : Promise.resolve(null)

  const [
    goalsMd,
    planText,
    bomText,
    issuesText,
    logText,
    assemblyMd,
    assemblyNotes,
    dfaText,
    legendText,
  ] = await Promise.all([
    gated('goals.md', 'goals.md'),
    gated('design_plan.md', 'design_plan.md'),
    gated('external/bom.md', 'external/bom.md'),
    gated('open_issues.md', 'open_issues.md'),
    gated('design_log.md', 'design_log.md'),
    gated('assembly/assembly.md', 'assembly/assembly.md'),
    gated('assembly/notes.md', 'assembly/notes.md'),
    gated('assembly/dfa_report.json', 'assembly/dfa_report.json'),
    gated('assembly/renders/color_legend.txt', 'assembly/renders/color_legend.txt'),
  ])

  const assemblyHasRenders = manifest
    ? manifest.files['assembly/renders'] === true
    : await fileExists(name, `assembly/renders/${STANDARD_RENDER_FILENAMES[0]}`)

  const designPlan = parseDesignPlan(planText)
  // Buy parts have no directory under assembly/ — only make/unknown parts are
  // loaded. A make part absent from the manifest (mid-run, no dir yet) gets an
  // empty map → all-absent, zero fetches.
  const parts = await Promise.all(
    designPlan.parts
      .filter((p) => p.kind !== 'buy')
      .map((p) => loadPart(name, p.name, manifest ? (manifest.parts[p.name] ?? {}) : null)),
  )

  return {
    name,
    goalsMd,
    designPlan,
    bom: parseBom(bomText),
    conflicts: parseConflicts(issuesText),
    logEntries: parseDesignLog(logText),
    parts,
    assembly: {
      md: assemblyMd ?? assemblyNotes,
      dfa: parseDfmaReport(dfaText),
      dfaRaw: dfaText,
      renders: assemblyHasRenders ? renderSet(name, 'assembly/renders') : [],
      legend: parseColorLegend(legendText),
    },
  }
}

/**
 * Load a SINGLE part for the part route — the part sheet needs only its own
 * PartModel, so assembling the whole project (and firing every other part's
 * probes) is wasted work. Returns null when the part has no directory (the
 * not-found signal). Falls back to probing when the manifest is unavailable.
 */
export async function loadSinglePart(
  project: string,
  partName: string,
): Promise<PartModel | null> {
  // design_plan.md (one small always-present fetch) tells us whether partName is
  // a planned make part — so a planned part whose assembly dir does not exist
  // yet (mid-run) renders a calm empty sheet, matching the old loadProject path,
  // rather than a hard "not found" (brief §3: mid-run absence is a normal state).
  const [manifest, planText] = await Promise.all([
    fetchManifest(project),
    fetchText(project, 'design_plan.md'),
  ])
  if (manifest === 'missing') return null // project does not exist
  const plannedMake = parseDesignPlan(planText).parts.some(
    (p) => p.name === partName && p.kind !== 'buy',
  )

  if (manifest) {
    const present = manifest.parts[partName]
    if (present) return loadPart(project, partName, present)
    // No dir yet: empty sheet if planned; otherwise genuinely not found.
    return plannedMake ? loadPart(project, partName, {}) : null
  }
  // No manifest — probe this one part; a dir that yielded nothing AND is not a
  // planned part = not found.
  const part = await loadPart(project, partName, null)
  const empty =
    !part.hasCode &&
    !part.hasRenders &&
    !part.constraintsMd &&
    !part.notesMd &&
    part.dfma === null &&
    part.attempts.length === 0 &&
    !part.proposalPending
  return empty && !plannedMake ? null : part
}
