// Renders ONE value out of `lead.answers`. Most answers are plain strings, but a
// step of type "file" (M16) stores an OBJECT — `{file_id, mime_type, name}` — or
// an ARRAY of them when the customer sent several files. Every place that shows
// answers (LeadCard, ConversationCard, ChatPanel's fallback, try-me) goes through
// this one component so a file answer can never render as "[object Object]".
//
// There are NO presigned URLs: the owner's browser hits the session-gated
// endpoint `GET /api/leads/files/{file_id}` directly and the session cookie rides
// along, so a plain <img src> / <a href> is all we need. The backend is the
// authority — it is tenant-scoped by RLS and 404s anything that isn't ours.

import type { AnswerValue as AnswerValueType, FileAnswer } from '../../dashboard/types'
import Icon from '../ui/Icon'

/** The owner-only download/stream URL for one stored file. */
export function fileUrl(fileId: string): string {
  return `/api/leads/files/${encodeURIComponent(fileId)}`
}

/** Narrow an unknown answer value to a single file answer. */
export function isFileAnswer(value: unknown): value is FileAnswer {
  return (
    typeof value === 'object' &&
    value !== null &&
    !Array.isArray(value) &&
    typeof (value as FileAnswer).file_id === 'string'
  )
}

/** Every file carried by an answer value ([] for a plain string answer). */
export function fileAnswers(value: AnswerValueType | null | undefined): FileAnswer[] {
  if (isFileAnswer(value)) return [value]
  if (Array.isArray(value)) return value.filter(isFileAnswer)
  return []
}

/** Does this answer hold at least one file? */
export function hasFileAnswer(value: AnswerValueType | null | undefined): boolean {
  return fileAnswers(value).length > 0
}

/** A short PLAIN-TEXT rendering — for `title=`, previews and aria labels.
 * Never returns "[object Object]". */
export function answerPreviewText(value: AnswerValueType | null | undefined): string {
  const files = fileAnswers(value)
  if (files.length > 0) {
    if (files.length === 1) return `📎 ${files[0].name?.trim() || 'קובץ'}`
    return `📎 ${files.length} קבצים`
  }
  return typeof value === 'string' ? value : ''
}

function isImage(file: FileAnswer): boolean {
  return (file.mime_type ?? '').toLowerCase().startsWith('image/')
}

function fileLabel(file: FileAnswer): string {
  return file.name?.trim() || (isImage(file) ? 'תמונה' : 'קובץ')
}

// --- one file -----------------------------------------------------------------

function FileChip({ file }: { file: FileAnswer }) {
  const href = fileUrl(file.file_id)
  const label = fileLabel(file)

  if (isImage(file)) {
    // Clickable thumbnail; opens the full-size image in a new tab.
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        title={`${label} — פתיחה בגודל מלא`}
        className="inline-block rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-leaf focus-visible:ring-offset-1"
      >
        <img
          src={href}
          alt={`תמונה שהלקוח שלח: ${label}`}
          loading="lazy"
          className="h-16 w-16 rounded-lg border border-black/10 object-cover dark:border-white/10"
        />
        <span className="sr-only">פתיחת התמונה בגודל מלא בלשונית חדשה</span>
      </a>
    )
  }

  return (
    <a
      href={href}
      download={file.name || undefined}
      className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-black/10 bg-slate-50 px-2 py-1 text-sm text-slate-800 outline-none transition-colors hover:bg-slate-100 focus-visible:ring-2 focus-visible:ring-leaf focus-visible:ring-offset-1 dark:border-white/10 dark:bg-slate-700 dark:text-slate-200 dark:hover:bg-slate-600"
    >
      <Icon name="download" size={15} className="flex-shrink-0 text-slate-400" />
      <span className="truncate">{label}</span>
      <span className="sr-only">— הורדת הקובץ</span>
    </a>
  )
}

// --- the value ----------------------------------------------------------------

type Props = {
  value: AnswerValueType | null | undefined
  /** Classes for the plain-string rendering (files always lay themselves out). */
  className?: string
  /** Shown when the answer is an empty string. */
  emptyLabel?: string
}

export default function AnswerValue({ value, className, emptyLabel = 'טרם נענה' }: Props) {
  const files = fileAnswers(value)

  if (files.length > 0) {
    return (
      <span className="flex flex-wrap items-center gap-1.5">
        {files.map((file, i) => (
          <FileChip key={`${file.file_id}-${i}`} file={file} />
        ))}
      </span>
    )
  }

  const text = typeof value === 'string' ? value : ''
  if (!text) return <span className="text-slate-400">{emptyLabel}</span>
  return <span className={className}>{text}</span>
}
