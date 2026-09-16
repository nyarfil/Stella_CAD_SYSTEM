/**
 * Client for the read-only projects API (plugins/projects-api.ts).
 * The filesystem is the API (PRD §2) — these helpers are the only data path.
 */

export interface ProjectSummary {
  name: string
  lastModified: string
  partCount: number
}

export async function fetchProjects(): Promise<ProjectSummary[]> {
  const res = await fetch('/api/projects')
  if (!res.ok) throw new Error(`GET /api/projects failed: ${res.status}`)
  return res.json()
}

/** Per-project file-existence map (plugins/projects-api.ts → /api/project/:name). */
export interface ProjectManifest {
  name: string
  files: Record<string, boolean>
  parts: Record<string, Record<string, boolean>>
}

/**
 * One server-side stat walk that tells the model which artifacts exist, so it
 * fetches only those instead of probing every conventional path (each absent
 * probe logged a console 404). Three outcomes, kept distinct so callers don't
 * conflate "project gone" with "endpoint down":
 *   - ProjectManifest — the project exists; gate fetches by it.
 *   - 'missing'       — 404: the project does not exist; do NOT probe (that was
 *                       the source of the ~24 console 404s on a bad project URL).
 *   - null            — endpoint unavailable; fall back to probing (PRD §2 degrade).
 */
export async function fetchManifest(name: string): Promise<ProjectManifest | 'missing' | null> {
  try {
    const res = await fetch(`/api/project/${encodeURIComponent(name)}`)
    if (res.ok) return (await res.json()) as ProjectManifest
    if (res.status === 404) return 'missing'
    return null
  } catch {
    return null
  }
}

/** URL for a raw file inside a project, e.g. assembly/renders/iso_clean.png */
export function projectFileUrl(project: string, relPath: string): string {
  const encoded = relPath.split('/').map(encodeURIComponent).join('/')
  return `/projects-fs/${encodeURIComponent(project)}/${encoded}`
}

export function relativeTime(iso: string): string {
  const deltaMs = new Date(iso).getTime() - Date.now()
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ['day', 86_400_000],
    ['hour', 3_600_000],
    ['minute', 60_000],
  ]
  const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })
  for (const [unit, ms] of units) {
    if (Math.abs(deltaMs) >= ms) return rtf.format(Math.round(deltaMs / ms), unit)
  }
  return 'just now'
}
