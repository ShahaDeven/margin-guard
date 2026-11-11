import type { Attachment } from '../lib/types'

/** Paperclip, drawn (no glyph icons). */
function Clip() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden className="shrink-0">
      <path d="M7.8 3.4 4.3 6.9a1 1 0 0 0 1.4 1.4l3.9-3.9a2 2 0 0 0-2.8-2.8L2.9 5.5a3 3 0 0 0 4.2 4.2L10 6.8"
        fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/** The files a supplier sent, each opening the original so an extracted price can be checked
 *  against it. A file that could not be read says why. */
export function Attachments({ files, className = '' }: { files: Attachment[]; className?: string }) {
  if (!files.length) return null
  return (
    <ul className={`flex flex-col gap-1 ${className}`}>
      {files.map((a) => (
        <li key={a.id} className="font-label text-[12px]">
          <a
            href={`/api/attachments/${a.id}`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 text-ink underline decoration-rule-bright underline-offset-2 hover:text-ink-bright"
          >
            <Clip />
            {a.filename}
          </a>
          {a.note ? <span className="ml-2 text-attn">{a.note}</span> : null}
        </li>
      ))}
    </ul>
  )
}
