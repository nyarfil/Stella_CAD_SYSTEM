import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

/**
 * Slice-local GFM renderer for assembly.md. Kept inside features/assembly/
 * until the shared MarkdownPanel (slice D) lands; integration swaps this out.
 */
export function MarkdownBlock({ md }: { md: string }) {
  return (
    <div className="min-w-0">
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: (props) => <h3 className="mt-4 mb-2 text-base font-medium first:mt-0" {...props} />,
          h2: (props) => <h4 className="mt-4 mb-2 text-sm font-medium first:mt-0" {...props} />,
          h3: (props) => (
            <h5
              className="mt-3 mb-1.5 text-2xs tracking-label uppercase text-ink-tertiary first:mt-0"
              {...props}
            />
          ),
          p: (props) => <p className="my-2 text-sm leading-6 text-ink-secondary" {...props} />,
          strong: (props) => <strong className="font-medium text-foreground" {...props} />,
          a: (props) => <a className="text-trace underline underline-offset-2" {...props} />,
          ul: (props) => (
            <ul className="my-2 list-disc space-y-1 pl-5 text-sm leading-6 text-ink-secondary" {...props} />
          ),
          ol: (props) => (
            <ol className="my-2 list-decimal space-y-1 pl-5 text-sm leading-6 text-ink-secondary" {...props} />
          ),
          code: (props) => (
            <code
              className="rounded-sm bg-surface-inset px-1 py-0.5 font-mono text-xs text-foreground"
              {...props}
            />
          ),
          pre: (props) => (
            <pre
              className="my-2 overflow-x-auto rounded-sm bg-surface-inset p-3 font-mono text-xs leading-5 [&_code]:bg-transparent [&_code]:p-0"
              {...props}
            />
          ),
          table: (props) => (
            <div className="my-2 overflow-x-auto">
              <table className="w-full border-collapse text-sm" {...props} />
            </div>
          ),
          th: (props) => (
            <th
              className="border-b border-stroke-object px-2 py-1.5 text-left text-2xs tracking-label uppercase text-ink-tertiary"
              {...props}
            />
          ),
          td: (props) => (
            <td
              className="border-b border-stroke-hairline px-2 py-1.5 align-top text-ink-secondary"
              {...props}
            />
          ),
          hr: () => <hr className="my-3 border-stroke-hairline" />,
        }}
      >
        {md}
      </Markdown>
    </div>
  )
}
