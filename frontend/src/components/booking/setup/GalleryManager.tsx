// מנהל תמונות הגלריה (M20) — העלאה, כיתוב, סידור ומחיקה
//
// The owner drops photos here and they appear on the public business page. The
// whole thing is built around "no save button": a caption commits on blur, a
// reorder commits the moment the image moves. The owner is not technical and
// should never have to remember to save.
//
// Ordering is kept honest by renumbering the whole list to 0..n-1 after every
// move and PATCHing only the rows whose number actually changed. The contract
// (§7) warns that duplicate sort_order values fall back to created_at, which
// looks to the owner like the reorder silently failed.
//
// Accessibility: dragging is an ENHANCEMENT, never the only route. Every image
// has real move-earlier / move-later buttons, so keyboard and touch users can
// order the gallery exactly as well as a mouse user can. Each caption input is a
// labelled control, and the caption doubles as the image's alt text.

import { useId, useRef, useState } from 'react'
import type { BusinessImage } from '../../../dashboard/businessPageTypes'
import { MAX_BUSINESS_IMAGES, imageSrc } from '../../../dashboard/businessPageTypes'
import {
  deleteBusinessImage,
  toUploadError,
  updateBusinessImage,
  uploadBusinessImage,
} from '../../../lib/businessPageClient'
import { shrinkImageForUpload } from '../../../lib/imageResize'
import { toFriendlyError } from '../../../lib/friendlyError'
import Alert from '../../ui/Alert'
import Icon from '../../ui/Icon'

const CAPTION_MAX = 120

type Props = {
  images: BusinessImage[]
  /** Replace the whole gallery in the parent's state (we own ordering here). */
  onImagesChange: (next: BusinessImage[]) => void
}

export default function GalleryManager({ images, onImagesChange }: Props) {
  const fileInputId = useId()
  const [dragOver, setDragOver] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Upload progress as 0..1 per queued filename slot, plus how many are left.
  const [uploading, setUploading] = useState<{ done: number; total: number; fraction: number } | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  // Index currently being dragged, for the drag-to-reorder enhancement.
  const dragIndex = useRef<number | null>(null)

  const remaining = MAX_BUSINESS_IMAGES - images.length
  const atCap = remaining <= 0
  const busy = uploading !== null

  // --- upload ---------------------------------------------------------------

  // Upload files one at a time. Serial on purpose: parallel uploads from a phone
  // fight for the same slow uplink and make the progress bar meaningless, and
  // the server's 40-cap check is per-request anyway.
  async function uploadFiles(files: File[]) {
    if (files.length === 0) return
    setError(null)

    // Local guard only — the server enforces the cap and can still say no (422).
    const allowed = files.slice(0, Math.max(0, remaining))
    if (allowed.length < files.length) {
      setError(
        `אפשר להעלות עד ${MAX_BUSINESS_IMAGES} תמונות בסך הכל. ` +
          `נוספו ${allowed.length} תמונות — למחוק תמונות קיימות כדי לפנות מקום.`,
      )
    }

    const added: BusinessImage[] = []
    for (let i = 0; i < allowed.length; i += 1) {
      setUploading({ done: i, total: allowed.length, fraction: 0 })
      try {
        const prepared = await shrinkImageForUpload(allowed[i])
        const created = await uploadBusinessImage(prepared, {
          onProgress: (fraction) =>
            setUploading({ done: i, total: allowed.length, fraction }),
        })
        added.push(created)
      } catch (err) {
        setError(toUploadError(err, 'העלאת התמונה נכשלה. נסו שוב.'))
        // A cap or file-type failure will repeat for every remaining file, so
        // stop here and show the reason once instead of N times.
        break
      }
    }

    setUploading(null)
    if (added.length > 0) onImagesChange([...images, ...added])
  }

  function pickFiles(ev: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(ev.target.files ?? [])
    // Reset so choosing the same file twice in a row still fires onChange.
    ev.target.value = ''
    void uploadFiles(files)
  }

  function drop(ev: React.DragEvent) {
    ev.preventDefault()
    setDragOver(false)
    if (atCap || busy) return
    const files = Array.from(ev.dataTransfer.files ?? []).filter((f) =>
      f.type.startsWith('image/'),
    )
    void uploadFiles(files)
  }

  // --- caption --------------------------------------------------------------

  // Saved on blur. An unchanged caption sends nothing at all — and an emptied
  // one sends explicit null, which is what CLEARS it (contract §7).
  async function saveCaption(image: BusinessImage, raw: string) {
    const next = raw.trim().slice(0, CAPTION_MAX) || null
    if (next === (image.caption ?? null)) return
    setBusyId(image.id)
    setError(null)
    try {
      const updated = await updateBusinessImage(image.id, { caption: next })
      onImagesChange(images.map((img) => (img.id === image.id ? updated : img)))
    } catch (err) {
      setError(toFriendlyError(err, 'שמירת הכיתוב נכשלה. נסו שוב.'))
    } finally {
      setBusyId(null)
    }
  }

  // --- ordering -------------------------------------------------------------

  // Move the image at `from` to `to`, renumber 0..n-1, and persist only the rows
  // whose sort_order actually moved. Optimistic: the grid reorders immediately
  // and we only fall back to the server's word if a PATCH fails.
  async function moveTo(from: number, to: number) {
    if (to < 0 || to >= images.length || from === to) return

    const reordered = [...images]
    const [moved] = reordered.splice(from, 1)
    reordered.splice(to, 0, moved)

    const renumbered = reordered.map((img, index) => ({ ...img, sort_order: index }))
    const changed = renumbered.filter(
      (img, index) => images.find((o) => o.id === img.id)?.sort_order !== index,
    )

    onImagesChange(renumbered)
    setBusyId(moved.id)
    setError(null)
    try {
      for (const img of changed) {
        await updateBusinessImage(img.id, { sort_order: img.sort_order })
      }
    } catch (err) {
      setError(toFriendlyError(err, 'שינוי הסדר נכשל. רעננו את העמוד ונסו שוב.'))
      onImagesChange(images) // put the grid back to what the server still believes
    } finally {
      setBusyId(null)
    }
  }

  // --- delete ---------------------------------------------------------------

  async function remove(image: BusinessImage) {
    const what = image.caption ? `"${image.caption}"` : 'התמונה הזו'
    if (!window.confirm(`למחוק את ${what}? המחיקה סופית ואי אפשר לשחזר.`)) return
    setBusyId(image.id)
    setError(null)
    try {
      await deleteBusinessImage(image.id)
      onImagesChange(images.filter((img) => img.id !== image.id))
    } catch (err) {
      setError(toFriendlyError(err, 'מחיקת התמונה נכשלה. נסו שוב.'))
    } finally {
      setBusyId(null)
    }
  }

  // --- render ---------------------------------------------------------------

  return (
    <div className="flex flex-col gap-4">
      {error ? <Alert tone="error">{error}</Alert> : null}

      {/* Drop zone + the plain file button. Both routes always available: drag
          alone would lock out anyone on a phone or using a keyboard. */}
      <div
        onDragOver={(ev) => {
          ev.preventDefault()
          if (!atCap && !busy) setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={drop}
        className={[
          'flex flex-col items-center gap-2 rounded-2xl border-2 border-dashed px-4 py-6 text-center transition sm:py-8',
          dragOver ? 'border-leaf bg-leaf-soft' : 'border-slate-300 bg-slate-50',
          atCap ? 'opacity-60' : '',
        ].join(' ')}
      >
        <Icon name="photo" size={28} className="text-slate-400" />
        <p className="text-sm font-medium text-slate-800">
          גררו לכאן תמונות של העסק
        </p>
        <p className="text-xs text-slate-500">JPG, PNG או WEBP · עד 5MB לתמונה</p>

        <label
          htmlFor={fileInputId}
          className={[
            'mt-1 inline-flex min-h-[44px] items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50 sm:min-h-0',
            atCap || busy ? 'pointer-events-none opacity-50' : 'cursor-pointer',
          ].join(' ')}
        >
          <Icon name="plus" size={16} />
          בחירת תמונות מהמחשב
        </label>
        <input
          id={fileInputId}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          multiple
          disabled={atCap || busy}
          onChange={pickFiles}
          className="sr-only"
        />

        <p className="text-xs text-slate-500" aria-live="polite">
          {atCap
            ? `הגעתם ל-${MAX_BUSINESS_IMAGES} תמונות — זה המקסימום. כדי להוסיף תמונה חדשה, מחקו קודם אחת קיימת.`
            : `${images.length} / ${MAX_BUSINESS_IMAGES} תמונות · אפשר להוסיף עוד ${remaining}`}
        </p>
      </div>

      {/* Upload progress. A 5MB photo on a phone takes real seconds. */}
      {uploading ? (
        <div role="status" aria-live="polite" className="flex flex-col gap-1.5">
          <span className="text-sm text-slate-700">
            מעלה תמונה {uploading.done + 1} מתוך {uploading.total}…
          </span>
          <span
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(uploading.fraction * 100)}
            aria-label="התקדמות ההעלאה"
            className="block h-2 w-full overflow-hidden rounded-full bg-slate-200"
          >
            <span
              className="block h-full rounded-full bg-leaf transition-all"
              style={{ width: `${Math.round(uploading.fraction * 100)}%` }}
            />
          </span>
        </div>
      ) : null}

      {images.length === 0 ? (
        <p className="rounded-xl border border-dashed border-slate-300 px-4 py-6 text-center text-sm text-slate-500">
          עדיין אין תמונות. התמונה הראשונה שתעלו תופיע בראש הגלריה בעמוד העסקי.
        </p>
      ) : (
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {images.map((image, index) => (
            <GalleryTile
              key={image.id}
              image={image}
              index={index}
              total={images.length}
              busy={busyId === image.id || busy}
              onCaptionBlur={(value) => void saveCaption(image, value)}
              onMove={(to) => void moveTo(index, to)}
              onDelete={() => void remove(image)}
              onDragStart={() => {
                dragIndex.current = index
              }}
              onDropOn={() => {
                const from = dragIndex.current
                dragIndex.current = null
                if (from !== null) void moveTo(from, index)
              }}
            />
          ))}
        </ul>
      )}
    </div>
  )
}

// One image in the grid: the thumbnail, its caption input, and the controls that
// move or delete it. The caption is held locally so typing doesn't re-render the
// whole grid, and committed on blur.
function GalleryTile({
  image,
  index,
  total,
  busy,
  onCaptionBlur,
  onMove,
  onDelete,
  onDragStart,
  onDropOn,
}: {
  image: BusinessImage
  index: number
  total: number
  busy: boolean
  onCaptionBlur: (value: string) => void
  onMove: (to: number) => void
  onDelete: () => void
  onDragStart: () => void
  onDropOn: () => void
}) {
  const captionId = useId()
  const [caption, setCaption] = useState(image.caption ?? '')

  const position = `תמונה ${index + 1} מתוך ${total}`

  return (
    <li
      draggable={!busy}
      onDragStart={onDragStart}
      onDragOver={(ev) => ev.preventDefault()}
      onDrop={(ev) => {
        ev.preventDefault()
        onDropOn()
      }}
      className="flex flex-col gap-2 rounded-xl border border-black/10 bg-white p-2"
    >
      <img
        src={imageSrc(image.storage_path)}
        // The caption IS the description — that's exactly what alt text is for.
        // With no caption the image is decorative next to its own controls.
        alt={image.caption ?? ''}
        loading="lazy"
        className="h-28 w-full rounded-lg bg-slate-100 object-cover"
      />

      <label htmlFor={captionId} className="sr-only">
        כיתוב ל{position}
      </label>
      <input
        id={captionId}
        value={caption}
        onChange={(ev) => setCaption(ev.target.value)}
        onBlur={() => onCaptionBlur(caption)}
        maxLength={CAPTION_MAX}
        disabled={busy}
        placeholder="כיתוב קצר…"
        className="w-full min-w-0 rounded-lg border border-slate-300 px-2 py-2 text-xs text-slate-900 placeholder:text-slate-400 disabled:opacity-60 sm:py-1"
      />

      {/* Two tiles per phone row leaves ~132px for controls, so the three buttons
          get p-2.5 (36px) there rather than the desktop p-1.5 (28px) — the
          largest target three of them still fit into. */}
      <div className="flex items-center justify-between">
        {/* Reordering without a mouse. In RTL, "earlier" is to the right. */}
        <div className="flex items-center gap-0.5">
          <button
            type="button"
            onClick={() => onMove(index - 1)}
            disabled={busy || index === 0}
            aria-label={`הזז את ${position} אחת קדימה`}
            className="rounded-lg p-2.5 text-slate-500 transition hover:bg-slate-100 disabled:opacity-30 sm:p-1.5"
          >
            <Icon name="chevron-right" size={16} />
          </button>
          <button
            type="button"
            onClick={() => onMove(index + 1)}
            disabled={busy || index === total - 1}
            aria-label={`הזז את ${position} אחת אחורה`}
            className="rounded-lg p-2.5 text-slate-500 transition hover:bg-slate-100 disabled:opacity-30 sm:p-1.5"
          >
            <Icon name="chevron-left" size={16} />
          </button>
          {/* Hidden on a phone: it is aria-hidden decoration, and its ~20px is
              the difference between 32px and 36px move/delete buttons in a
              132px-wide tile. The order is legible from the grid itself. */}
          <span aria-hidden="true" className="hidden px-1 text-xs text-slate-400 sm:inline">
            {index + 1}
          </span>
        </div>

        <button
          type="button"
          onClick={onDelete}
          disabled={busy}
          aria-label={`מחק את ${position}`}
          className="rounded-lg p-2.5 text-slate-400 transition hover:bg-red-50 hover:text-bad disabled:opacity-40 sm:p-1.5"
        >
          <Icon name="trash" size={16} />
        </button>
      </div>
    </li>
  )
}
