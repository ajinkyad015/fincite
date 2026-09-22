import { memo, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Renders assistant markdown. Inline citation markers [1] [2] are
 * rewritten into links (#cite-n) and rendered as clickable chips.
 */
function CiteMarkdown({
  content,
  onCite,
}: {
  content: string;
  onCite: (n: number) => void;
}) {
  const processed = useMemo(
    () => content.replace(/\[(\d{1,2})\]/g, (_m, n) => `[${n}](#cite-${n})`),
    [content]
  );

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: ({ href, children }) => {
          if (href?.startsWith("#cite-")) {
            const n = Number(href.slice(6));
            return (
              <button
                type="button"
                onClick={() => onCite(n)}
                aria-label={`Open source ${n}`}
                className="tnum mx-[1px] inline-flex h-[17px] min-w-[17px] -translate-y-[3px] items-center justify-center border border-line bg-paper px-[3px] align-middle font-mono text-[10px] font-medium leading-none text-accent-deep transition-colors hover:border-accent hover:bg-accent hover:text-paper"
              >
                {children}
              </button>
            );
          }
          return (
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="text-accent-deep underline decoration-line underline-offset-2 hover:decoration-accent"
            >
              {children}
            </a>
          );
        },
        p: ({ children }) => (
          <p className="my-3 text-[15px] leading-[1.78] text-ink/85 first:mt-0 last:mb-0">
            {children}
          </p>
        ),
        strong: ({ children }) => (
          <strong className="font-semibold text-ink">{children}</strong>
        ),
        em: ({ children }) => (
          <em className="font-display italic text-ink/90">{children}</em>
        ),
        h2: ({ children }) => (
          <h2 className="mt-6 mb-2 font-display text-xl font-semibold text-ink">{children}</h2>
        ),
        h3: ({ children }) => (
          <h3 className="mt-5 mb-1.5 font-display text-[17px] font-semibold text-ink">{children}</h3>
        ),
        ul: ({ children }) => (
          <ul className="my-3 list-disc space-y-1.5 pl-5 text-[15px] leading-[1.72] text-ink/85 marker:text-accent">
            {children}
          </ul>
        ),
        ol: ({ children }) => (
          <ol className="my-3 list-decimal space-y-1.5 pl-5 text-[15px] leading-[1.72] text-ink/85 marker:font-mono marker:text-[12px] marker:text-moss">
            {children}
          </ol>
        ),
        blockquote: ({ children }) => (
          <blockquote className="my-4 border-l-2 border-accent bg-accent-soft/40 py-2.5 pl-4 pr-3 font-display text-[15px] italic leading-[1.7] text-ink/80">
            {children}
          </blockquote>
        ),
        table: ({ children }) => (
          <div className="my-4 overflow-x-auto border-y border-line py-1">
            <table className="md-table min-w-[420px]">{children}</table>
          </div>
        ),
        code: ({ children }) => (
          <code className="border border-line bg-faint px-1 py-0.5 font-mono text-[12.5px] text-accent-deep">
            {children}
          </code>
        ),
        hr: () => <hr className="my-6 border-line" />,
      }}
    >
      {processed}
    </ReactMarkdown>
  );
}

export default memo(CiteMarkdown);
