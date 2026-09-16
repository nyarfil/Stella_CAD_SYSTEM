/**
 * Render artifacts from tools.renderer: every run writes the same 8 PNGs
 * (4 views x 2 styles) named `<view>_<style>.png` into a renders/ directory;
 * assembly runs also write color_legend.txt with lines like
 * `  base_box: red (RGB 220,40,40)`. The legend's RGB triple is the actual
 * stroke color — CSS color names only approximate it.
 */

export type RenderView = 'front' | 'top' | 'right' | 'iso'
export type RenderStyle = 'clean' | 'wireframe'

export interface RenderFile {
  view: RenderView
  style: RenderStyle
  filename: string
  url: string
}

export type RenderSet = RenderFile[]

export interface LegendEntry {
  part: string
  /** Color name as written, e.g. "red". */
  color: string
  /** Exact stroke color as a CSS string, e.g. "rgb(220,40,40)"; null if unparsed. */
  rgb: string | null
}

export const RENDER_VIEWS: readonly RenderView[] = ['front', 'top', 'right', 'iso']
export const RENDER_STYLES: readonly RenderStyle[] = ['clean', 'wireframe']

/** The renderer's full 8-file set, view-major, clean before wireframe. */
export const STANDARD_RENDER_FILENAMES: readonly string[] = RENDER_VIEWS.flatMap((view) =>
  RENDER_STYLES.map((style) => `${view}_${style}.png`),
)

const RENDER_NAME = /^(front|top|right|iso)_(clean|wireframe)\.png$/

/**
 * Typed render descriptors for the filenames that follow the renderer's
 * naming scheme (others — color_legend.txt, stray files — are dropped).
 * Output is sorted view-major then clean-first for stable display order.
 */
export function parseRenderFilenames(
  filenames: readonly string[],
  urlFor: (filename: string) => string,
): RenderSet {
  const files: RenderFile[] = []
  for (const filename of filenames) {
    const m = filename.match(RENDER_NAME)
    if (!m) continue
    files.push({
      view: m[1] as RenderView,
      style: m[2] as RenderStyle,
      filename,
      url: urlFor(filename),
    })
  }
  files.sort(
    (a, b) =>
      RENDER_VIEWS.indexOf(a.view) - RENDER_VIEWS.indexOf(b.view) ||
      RENDER_STYLES.indexOf(a.style) - RENDER_STYLES.indexOf(b.style),
  )
  return files
}

const LEGEND_LINE = /^\s*(.+?):\s*([A-Za-z][\w-]*)\s*(?:\(RGB\s*([\d\s,]+)\))?\s*$/

export function parseColorLegend(text: string | null | undefined): LegendEntry[] {
  if (!text) return []
  const entries: LegendEntry[] = []
  for (const line of text.split('\n')) {
    const m = line.match(LEGEND_LINE)
    if (!m) continue
    const nums = m[3] ? m[3].split(/[\s,]+/).filter(Boolean) : []
    entries.push({
      part: m[1].trim(),
      color: m[2],
      rgb: nums.length === 3 ? `rgb(${nums.join(',')})` : null,
    })
  }
  return entries
}
