import { Highlight, type PrismTheme } from 'prism-react-renderer'
import { cn } from '@/lib/utils'

interface CodeBlockProps {
  code: string
  className?: string
}

/* RESTRAINED drafting-pencil theme — maps Python token types to design-system CSS vars
   (theme-adaptive: vars flip dark↔light). NO hard-coded hex colors (defeats theming).
   Aesthetic: comments recede (ink-faint italic), strings muted green (pass-ink), keywords
   brightest (foreground), functions pencil-blue (trace), numbers faint ochre (note-ink),
   punctuation quiet (ink-tertiary). Reads as "drafting pencil highlight" not rainbow. */
const draftingTheme: PrismTheme = {
  plain: { color: 'var(--ink-secondary)' },
  styles: [
    {
      types: ['comment', 'prolog', 'doctype', 'cdata'],
      style: { color: 'var(--ink-faint)', fontStyle: 'italic' },
    },
    {
      types: ['keyword'],
      style: { color: 'var(--foreground)' },
    },
    {
      types: ['string', 'char'],
      style: { color: 'var(--pass-ink)' },
    },
    {
      types: ['number', 'boolean'],
      style: { color: 'var(--note-ink)' },
    },
    {
      types: ['function'],
      style: { color: 'var(--trace)' },
    },
    {
      types: ['class-name'],
      style: { color: 'var(--warn-ink)' },
    },
    {
      types: ['operator', 'punctuation'],
      style: { color: 'var(--ink-tertiary)' },
    },
    {
      types: ['builtin', 'constant'],
      style: { color: 'var(--ink-secondary)' },
    },
    {
      types: ['decorator', 'annotation'],
      style: { color: 'var(--trace)' },
    },
  ],
}

export function CodeBlock({ code, className }: CodeBlockProps) {
  // Trim single trailing newline to match current CodePanel behavior
  const normalized = code.replace(/\n$/, '')

  return (
    <Highlight code={normalized} language="python" theme={draftingTheme}>
      {({ tokens, getLineProps, getTokenProps }) => (
        <div
          className={cn(
            'max-h-[32rem] overflow-auto rounded-md border border-stroke-hairline bg-surface-inset',
            className,
          )}
        >
          <pre className="min-w-full py-2 font-mono text-xs leading-relaxed">
            <code>
              {tokens.map((line, i) => (
                <div key={i} {...getLineProps({ line })} className="grid grid-cols-[3rem_1fr]">
                  <span className="select-none px-2 text-right text-ink-faint tabular-nums">
                    {i + 1}
                  </span>
                  <span className="whitespace-pre px-2">
                    {line.length === 0 ? (
                      // Preserve blank lines as height (non-breaking space)
                      <span>&nbsp;</span>
                    ) : (
                      line.map((token, key) => <span key={key} {...getTokenProps({ token })} />)
                    )}
                  </span>
                </div>
              ))}
            </code>
          </pre>
        </div>
      )}
    </Highlight>
  )
}
