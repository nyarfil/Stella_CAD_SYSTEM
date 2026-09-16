/**
 * Read-only filesystem API for the harness `projects/` tree.
 *
 * PRD §2 invariant: the filesystem IS the API. This Vite middleware is the
 * frontend's only bridge to harness state — it never imports harness code,
 * never writes, and is confined to PROJECTS_ROOT (path-traversal guarded).
 *
 * Routes:
 *   GET /api/projects                     → [{ name, lastModified, partCount }]
 *   GET /api/project/<name>               → project manifest (existence map; see ProjectManifest below)
 *   GET /api/activity/<project>           → activity aggregation (lanes + events; see the aggregation block below)
 *   GET /projects-fs/<project>/<relpath>  → raw file bytes (renders, markdown, json, code)
 */
import type { Plugin, ViteDevServer, PreviewServer } from 'vite'
import type { IncomingMessage, ServerResponse } from 'node:http'
import fs from 'node:fs/promises'
import path from 'node:path'

export const PROJECTS_ROOT = path.resolve(import.meta.dirname, '..', '..', 'projects')

const MIME: Record<string, string> = {
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.md': 'text/markdown; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.py': 'text/plain; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8',
}

interface ProjectSummary {
  name: string
  /** ISO timestamp of the most recent write anywhere in the project tree. */
  lastModified: string
  /** Directories under assembly/ excluding renders/ — one per part. */
  partCount: number
}

/**
 * Per-project existence map. The client used to PROBE conventional paths (a GET
 * per optional artifact), logging red 404s for every absent optional file
 * (part.proposal.py, incomplete-run docs) — doubled by StrictMode. This map
 * lets the client fetch only files that exist. Still pure read-only stat work.
 */
interface ProjectManifest {
  name: string
  /** Canonical top-level + assembly-level paths → exists. */
  files: Record<string, boolean>
  /** partName → { conventional part file → exists }. */
  parts: Record<string, Record<string, boolean>>
}

/** Top-level + assembly files the client conditionally loads (mirror lib/model.ts). */
const PROJECT_FILE_KEYS = [
  'goals.md',
  'design_plan.md',
  'external/bom.md',
  'open_issues.md',
  'design_log.md',
  'assembly/assembly.md',
  'assembly/notes.md',
  'assembly/dfa_report.json',
  'assembly/renders/color_legend.txt',
] as const

/** Per-part files the client conditionally loads (mirror lib/model.ts loadPart). */
const PART_FILE_KEYS = [
  'constraints.md',
  'notes.md',
  'dfma_report.json',
  'attempt_log.json',
  'part.py',
  'part.proposal.py',
] as const

async function isFile(abs: string): Promise<boolean> {
  const stat = await fs.stat(abs).catch(() => null)
  return stat?.isFile() ?? false
}

/** renders/ presence = the dir holds ≥1 .png (the renderer emits the 8 standard views together). */
async function dirHasPng(abs: string): Promise<boolean> {
  const entries = await fs.readdir(abs, { withFileTypes: true }).catch(() => null)
  return entries ? entries.some((e) => e.isFile() && e.name.endsWith('.png')) : false
}

async function buildManifest(projectDir: string, name: string): Promise<ProjectManifest> {
  const files: Record<string, boolean> = {}
  await Promise.all(
    PROJECT_FILE_KEYS.map(async (key) => {
      files[key] = await isFile(path.join(projectDir, key))
    }),
  )
  files['assembly/renders'] = await dirHasPng(path.join(projectDir, 'assembly', 'renders'))

  const assemblyDir = path.join(projectDir, 'assembly')
  const assemblyEntries = await fs.readdir(assemblyDir, { withFileTypes: true }).catch(() => [])
  const partDirs = assemblyEntries
    .filter((e) => e.isDirectory() && e.name !== 'renders' && !e.name.startsWith('.'))
    .map((e) => e.name)

  const parts: Record<string, Record<string, boolean>> = {}
  await Promise.all(
    partDirs.map(async (part) => {
      const partDir = path.join(assemblyDir, part)
      const map: Record<string, boolean> = {}
      await Promise.all(
        PART_FILE_KEYS.map(async (key) => {
          map[key] = await isFile(path.join(partDir, key))
        }),
      )
      map['renders'] = await dirHasPng(path.join(partDir, 'renders'))
      parts[part] = map
    }),
  )

  return { name, files, parts }
}

/** Max mtime across the tree — dir mtimes alone miss nested writes. */
async function latestMtime(dir: string, depth = 0): Promise<number> {
  if (depth > 6) return 0
  let latest = 0
  let entries
  try {
    entries = await fs.readdir(dir, { withFileTypes: true })
  } catch {
    return 0
  }
  for (const entry of entries) {
    if (entry.name.startsWith('.')) continue
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      latest = Math.max(latest, await latestMtime(full, depth + 1))
    } else {
      const stat = await fs.stat(full).catch(() => null)
      if (stat) latest = Math.max(latest, stat.mtimeMs)
    }
  }
  return latest
}

async function listProjects(): Promise<ProjectSummary[]> {
  const entries = await fs.readdir(PROJECTS_ROOT, { withFileTypes: true }).catch(() => [])
  const projects: ProjectSummary[] = []
  for (const entry of entries) {
    if (!entry.isDirectory() || entry.name.startsWith('.')) continue
    const projectDir = path.join(PROJECTS_ROOT, entry.name)
    const assemblyDir = path.join(projectDir, 'assembly')
    const assemblyEntries = await fs.readdir(assemblyDir, { withFileTypes: true }).catch(() => [])
    const partCount = assemblyEntries.filter(
      (e) => e.isDirectory() && e.name !== 'renders' && !e.name.startsWith('.'),
    ).length
    const mtime = await latestMtime(projectDir)
    projects.push({
      name: entry.name,
      lastModified: new Date(mtime || Date.now()).toISOString(),
      partCount,
    })
  }
  projects.sort((a, b) => b.lastModified.localeCompare(a.lastModified))
  return projects
}

// ---------------------------------------------------------------------------
// Activity aggregation.
// One server-side walk per request: attempt_log.json JSONL (timestamps),
// design_log.md `[agent] message` lines (ordinal, no timestamps), artifact
// mtimes. All v1 spans are approximate (`approx: true`).
// ---------------------------------------------------------------------------

const ACTIVE_WINDOW_MS = 10 * 60 * 1000
/** Span width when a lane has no previous event to chain a start from. */
const SPAN_EPSILON_MS = 60 * 1000
const LABEL_MAX = 140

interface ActivityEvent {
  seq: number
  ts: string | null
  agent: string
  part: string | null
  kind: 'attempt' | 'artifact' | 'log'
  label: string
  outcome: 'success' | 'failed' | null
}

interface ActivitySpan {
  startTs: string | null
  endTs: string
  part: string | null
  approx: boolean
  label: string
}

interface ActivityLane {
  agent: string
  spans: ActivitySpan[]
}

type PendingEvent = Omit<ActivityEvent, 'seq'>

/**
 * Assembly-level attempt logs carry date-only `ts` ("2026-07-13") — parsing
 * those to midnight would distort the time axis, so only timestamps with a
 * time component count.
 */
function isoWithTime(raw: unknown): string | null {
  if (typeof raw !== 'string' || !raw.includes('T')) return null
  const ms = Date.parse(raw)
  return Number.isFinite(ms) ? new Date(ms).toISOString() : null
}

function normalizeOutcome(raw: unknown): 'success' | 'failed' | null {
  if (typeof raw !== 'string') return null
  const value = raw.toLowerCase()
  if (value.startsWith('success') || value.startsWith('pass') || value === 'promoted') return 'success'
  if (value.startsWith('fail') || value === 'rejected') return 'failed'
  return null
}

function clipLabel(raw: string): string {
  const flat = raw.replace(/\s+/g, ' ').trim()
  return flat.length > LABEL_MAX ? `${flat.slice(0, LABEL_MAX - 1)}…` : flat
}

/**
 * attempt_log.json is JSONL with heterogeneous entries: designer attempts use
 * `role`/`outcome`, gate events use `event`/`verdict`, repair uses `result`,
 * assembly-level entries use `who`, some gate entries use `actor`/`timestamp`.
 * Unparseable lines are skipped silently.
 */
async function readAttemptEvents(file: string, fallbackPart: string | null): Promise<PendingEvent[]> {
  let text: string
  try {
    text = await fs.readFile(file, 'utf-8')
  } catch {
    return []
  }
  const events: PendingEvent[] = []
  for (const line of text.split('\n')) {
    if (!line.trim()) continue
    let entry: Record<string, unknown>
    try {
      entry = JSON.parse(line)
    } catch {
      continue
    }
    if (!entry || typeof entry !== 'object') continue
    const agent =
      (typeof entry.role === 'string' && entry.role) ||
      (typeof entry.who === 'string' && entry.who) ||
      (typeof entry.actor === 'string' && entry.actor) ||
      'unknown'
    const label =
      [entry.action, entry.event, entry.targeted, entry.approach].find(
        (v): v is string => typeof v === 'string' && v.length > 0,
      ) ?? 'attempt'
    events.push({
      ts: isoWithTime(entry.ts ?? entry.timestamp),
      agent,
      part: typeof entry.part === 'string' ? entry.part : fallbackPart,
      kind: 'attempt',
      label: clipLabel(label),
      outcome: normalizeOutcome(entry.outcome ?? entry.verdict ?? entry.result),
    })
  }
  return events
}

async function artifactEvent(
  file: string,
  agent: string,
  part: string | null,
  label: string,
): Promise<PendingEvent | null> {
  const stat = await fs.stat(file).catch(() => null)
  if (!stat?.isFile()) return null
  return { ts: new Date(stat.mtimeMs).toISOString(), agent, part, kind: 'artifact', label, outcome: null }
}

/** One event per renders/ dir (latest .png mtime) — 8 per-view dots per part would drown the strip. */
async function rendersEvent(dir: string, agent: string, part: string | null): Promise<PendingEvent | null> {
  const entries = await fs.readdir(dir, { withFileTypes: true }).catch(() => null)
  if (!entries) return null
  let latest = 0
  let count = 0
  for (const entry of entries) {
    if (!entry.isFile() || !entry.name.endsWith('.png')) continue
    const stat = await fs.stat(path.join(dir, entry.name)).catch(() => null)
    if (!stat) continue
    count += 1
    latest = Math.max(latest, stat.mtimeMs)
  }
  if (count === 0) return null
  return {
    ts: new Date(latest).toISOString(),
    agent,
    part,
    kind: 'artifact',
    label: `renders (${count})`,
    outcome: null,
  }
}

const LOG_LINE = /^\[([A-Za-z0-9_-]+)\]\s+(.+)$/
const LOG_FAILED = /\b(FAILED|REJECTED)\b/
const LOG_SUCCESS = /\b(PASSED|VALIDATED|PROMOTED)\b|\bsuccess\b/i

function parseDesignLog(text: string, knownParts: Set<string>): PendingEvent[] {
  const events: PendingEvent[] = []
  for (const line of text.split('\n')) {
    const match = LOG_LINE.exec(line.trim())
    if (!match) continue
    const [, agent, message] = match
    const partMatch = /^(?:fresh\s+)?([a-z0-9_]+)\s*:/i.exec(message)
    const partCandidate = partMatch?.[1].toLowerCase()
    events.push({
      ts: null,
      agent,
      part: partCandidate && knownParts.has(partCandidate) ? partCandidate : null,
      kind: 'log',
      label: clipLabel(message),
      outcome: LOG_FAILED.test(message) ? 'failed' : LOG_SUCCESS.test(message) ? 'success' : null,
    })
  }
  return events
}

function buildLanes(events: ActivityEvent[]): ActivityLane[] {
  const byAgent = new Map<string, ActivityEvent[]>()
  for (const event of events) {
    const lane = byAgent.get(event.agent)
    if (lane) lane.push(event)
    else byAgent.set(event.agent, [event])
  }
  const lanes: ActivityLane[] = []
  for (const [agent, agentEvents] of byAgent) {
    const timed = agentEvents
      .filter((e): e is ActivityEvent & { ts: string } => e.ts !== null)
      .sort((a, b) => a.ts.localeCompare(b.ts))
    const spans: ActivitySpan[] = []
    let prevEnd: string | null = null
    for (const event of timed) {
      // Spec §3: end = attempt ts or artifact mtime; start = previous end on this lane, else end − ε.
      const startTs = prevEnd ?? new Date(Date.parse(event.ts) - SPAN_EPSILON_MS).toISOString()
      spans.push({ startTs, endTs: event.ts, part: event.part, approx: true, label: event.label })
      prevEnd = event.ts
    }
    lanes.push({ agent, spans })
  }
  return lanes
}

async function collectActivity(projectDir: string) {
  const assemblyDir = path.join(projectDir, 'assembly')
  const assemblyEntries = await fs.readdir(assemblyDir, { withFileTypes: true }).catch(() => [])
  const parts = assemblyEntries
    .filter((e) => e.isDirectory() && e.name !== 'renders' && !e.name.startsWith('.'))
    .map((e) => e.name)

  const pending: PendingEvent[] = []

  for (const part of parts) {
    const partDir = path.join(assemblyDir, part)
    pending.push(...(await readAttemptEvents(path.join(partDir, 'attempt_log.json'), part)))
    for (const [file, agent] of [
      ['part.py', 'cad_designer'],
      ['notes.md', 'cad_designer'],
      ['dfma_report.json', 'validator'],
    ] as const) {
      const event = await artifactEvent(path.join(partDir, file), agent, part, file)
      if (event) pending.push(event)
    }
    const renders = await rendersEvent(path.join(partDir, 'renders'), 'cad_designer', part)
    if (renders) pending.push(renders)
  }

  pending.push(...(await readAttemptEvents(path.join(assemblyDir, 'attempt_log.json'), null)))
  for (const file of ['assembly.py', 'notes.md'] as const) {
    const event = await artifactEvent(path.join(assemblyDir, file), 'assembly_resolver', null, file)
    if (event) pending.push(event)
  }
  const assemblyRenders = await rendersEvent(path.join(assemblyDir, 'renders'), 'assembly_resolver', null)
  if (assemblyRenders) pending.push(assemblyRenders)

  let hasTerminalMarker = false
  for (const file of ['checkpoint.md', 'smoke_report.md'] as const) {
    const event = await artifactEvent(path.join(projectDir, file), 'orchestrator', null, file)
    if (event) {
      pending.push(event)
      hasTerminalMarker = true
    }
  }

  const logText = await fs.readFile(path.join(projectDir, 'design_log.md'), 'utf-8').catch(() => '')
  const logEvents = parseDesignLog(logText, new Set(parts))
  pending.push(...logEvents)

  // Timestamped events in time order; log lines (no ts) keep ordinal order at
  // the tail — the design_log is the freshest narrative, so the newest event
  // is always the latest log line.
  const timed = pending.filter((e): e is PendingEvent & { ts: string } => e.ts !== null)
  timed.sort((a, b) => a.ts.localeCompare(b.ts))
  const untimed = pending.filter((e) => e.ts === null)
  const events: ActivityEvent[] = [...timed, ...untimed].map((event, seq) => ({ seq, ...event }))

  // Terminal = checkpoint/smoke marker present AND the log's LAST line says
  // "Session ended" — a mid-run checkpoint alone is not terminal (sessions
  // resume from it). Test the raw line, not the clipped label.
  const rawLogLines = logText.split('\n').filter((line) => LOG_LINE.test(line.trim()))
  const lastRawLine = rawLogLines.length > 0 ? rawLogLines[rawLogLines.length - 1] : ''
  const terminal = hasTerminalMarker && lastRawLine.includes('Session ended')
  const newestMtime = await latestMtime(projectDir)
  const lastLog = logEvents.length > 0 ? logEvents[logEvents.length - 1] : null

  return {
    generatedAt: new Date().toISOString(),
    isActive: !terminal && Date.now() - newestMtime < ACTIVE_WINDOW_MS,
    activeAgent: lastLog?.agent ?? null,
    events,
    lanes: buildLanes(events),
  }
}

function sendJson(res: ServerResponse, status: number, body: unknown) {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json; charset=utf-8')
  res.end(JSON.stringify(body))
}

async function handle(req: IncomingMessage, res: ServerResponse): Promise<boolean> {
  const url = new URL(req.url ?? '/', 'http://localhost')

  if (url.pathname === '/api/projects') {
    if (req.method !== 'GET') {
      sendJson(res, 405, { error: 'read-only API' })
      return true
    }
    sendJson(res, 200, await listProjects())
    return true
  }

  if (url.pathname.startsWith('/api/project/')) {
    if (req.method !== 'GET') {
      sendJson(res, 405, { error: 'read-only API' })
      return true
    }
    let name: string
    try {
      name = decodeURIComponent(url.pathname.slice('/api/project/'.length))
    } catch {
      sendJson(res, 404, { error: 'bad project name' })
      return true
    }
    if (!name || name.includes('/') || name.includes('\\') || name.startsWith('.')) {
      sendJson(res, 404, { error: `not found: ${name || '(empty)'}` })
      return true
    }
    const projectDir = path.resolve(PROJECTS_ROOT, name)
    if (!projectDir.startsWith(PROJECTS_ROOT + path.sep)) {
      sendJson(res, 403, { error: 'path escapes projects root' })
      return true
    }
    const stat = await fs.stat(projectDir).catch(() => null)
    if (!stat?.isDirectory()) {
      sendJson(res, 404, { error: `not found: ${name}` })
      return true
    }
    sendJson(res, 200, await buildManifest(projectDir, name))
    return true
  }

  if (url.pathname.startsWith('/api/activity/')) {
    if (req.method !== 'GET') {
      sendJson(res, 405, { error: 'read-only API' })
      return true
    }
    let name: string
    try {
      name = decodeURIComponent(url.pathname.slice('/api/activity/'.length))
    } catch {
      sendJson(res, 404, { error: 'bad project name' })
      return true
    }
    if (!name || name.includes('/') || name.includes('\\') || name.startsWith('.')) {
      sendJson(res, 404, { error: `not found: ${name || '(empty)'}` })
      return true
    }
    const projectDir = path.resolve(PROJECTS_ROOT, name)
    if (!projectDir.startsWith(PROJECTS_ROOT + path.sep)) {
      sendJson(res, 403, { error: 'path escapes projects root' })
      return true
    }
    const stat = await fs.stat(projectDir).catch(() => null)
    if (!stat?.isDirectory()) {
      sendJson(res, 404, { error: `not found: ${name}` })
      return true
    }
    try {
      sendJson(res, 200, await collectActivity(projectDir))
    } catch {
      sendJson(res, 500, { error: 'activity aggregation failed' })
    }
    return true
  }

  if (url.pathname.startsWith('/projects-fs/')) {
    if (req.method !== 'GET') {
      sendJson(res, 405, { error: 'read-only API' })
      return true
    }
    const rel = decodeURIComponent(url.pathname.slice('/projects-fs/'.length))
    const resolved = path.resolve(PROJECTS_ROOT, rel)
    if (!resolved.startsWith(PROJECTS_ROOT + path.sep)) {
      sendJson(res, 403, { error: 'path escapes projects root' })
      return true
    }
    try {
      const data = await fs.readFile(resolved)
      res.statusCode = 200
      res.setHeader('Content-Type', MIME[path.extname(resolved)] ?? 'application/octet-stream')
      res.end(data)
    } catch {
      sendJson(res, 404, { error: `not found: ${rel}` })
    }
    return true
  }

  return false
}

function attach(server: ViteDevServer | PreviewServer) {
  server.middlewares.use((req, res, next) => {
    handle(req, res).then((handled) => {
      if (!handled) next()
    }, next)
  })
}

export default function projectsApi(): Plugin {
  return {
    name: 'ai-cad-projects-api',
    configureServer: attach,
    configurePreviewServer: attach,
  }
}
