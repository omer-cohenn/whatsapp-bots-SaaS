// Services CRUD: list every service (name, duration, optional description +
// price, active toggle), edit them inline, add a new one, and delete. Each
// mutation hits the admin API directly and then asks the parent to refetch the
// list (so we never drift from server truth). The tenant is server-side only —
// we send no business_id.
//
// description (≤500) + price (whole ₪, ≥0) are both OPTIONAL. An empty price
// means "no price" → the public card shows "ללא עלות". Sending `null` on a PATCH
// CLEARS that column; omitting it leaves it unchanged.
//
// Accessibility: the add form is a real <form> (Enter submits), every input is
// labelled, destructive delete asks for confirm, and async state is announced.

import { useState } from 'react'
import type { ServiceItem, ServiceUpdate } from '../../dashboard/appointmentTypes'
import { createService, deleteService, updateService } from '../../lib/bookingClient'
import { toFriendlyError } from '../../lib/friendlyError'
import Field from '../ui/Field'
import Textarea from '../ui/Textarea'
import Button from '../ui/Button'
import Icon from '../ui/Icon'

type Props = {
  services: ServiceItem[]
  /** Called after any successful create/update/delete so the parent reloads. */
  onChanged: () => void
}

// Parse the price input: '' → null (no price); otherwise a non-negative integer.
// Returns `undefined` to signal an INVALID value (negative / non-numeric).
function parsePrice(raw: string): number | null | undefined {
  const trimmed = raw.trim()
  if (trimmed === '') return null
  const n = Number(trimmed)
  if (!Number.isInteger(n) || n < 0) return undefined
  return n
}

export default function ServicesEditor({ services, onChanged }: Props) {
  const [newName, setNewName] = useState('')
  const [newDuration, setNewDuration] = useState('30')
  const [newDescription, setNewDescription] = useState('')
  const [newPrice, setNewPrice] = useState('')
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Per-row "busy" so only the touched service shows a spinner/disables.
  const [busyId, setBusyId] = useState<string | null>(null)

  async function add(ev: React.FormEvent) {
    ev.preventDefault()
    const name = newName.trim()
    const duration = Number(newDuration)
    if (!name || !Number.isFinite(duration) || duration <= 0) {
      setError('יש להזין שם שירות ומשך זמן חיובי.')
      return
    }
    const price = parsePrice(newPrice)
    if (price === undefined) {
      setError('המחיר חייב להיות מספר שלם אי-שלילי (₪).')
      return
    }
    setAdding(true)
    setError(null)
    try {
      await createService({
        name,
        duration_minutes: duration,
        active: true,
        description: newDescription.trim() || null,
        price,
      })
      setNewName('')
      setNewDuration('30')
      setNewDescription('')
      setNewPrice('')
      onChanged()
    } catch (err) {
      setError(toFriendlyError(err, 'הוספת השירות נכשלה. נסו שוב.'))
    } finally {
      setAdding(false)
    }
  }

  async function patch(id: string, body: ServiceUpdate) {
    setBusyId(id)
    setError(null)
    try {
      await updateService(id, body)
      onChanged()
    } catch (err) {
      setError(toFriendlyError(err, 'עדכון השירות נכשל. נסו שוב.'))
    } finally {
      setBusyId(null)
    }
  }

  async function remove(svc: ServiceItem) {
    if (!window.confirm(`למחוק את השירות "${svc.name}"?`)) return
    setBusyId(svc.id)
    setError(null)
    try {
      await deleteService(svc.id)
      onChanged()
    } catch (err) {
      setError(toFriendlyError(err, 'מחיקת השירות נכשלה. נסו שוב.'))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {error ? (
        <p role="alert" className="text-sm text-bad">
          {error}
        </p>
      ) : null}

      {/* Existing services */}
      {services.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {services.map((svc) => (
            <ServiceRow
              key={svc.id}
              service={svc}
              busy={busyId === svc.id}
              onSave={(body) => void patch(svc.id, body)}
              onToggleActive={() => void patch(svc.id, { active: !svc.active })}
              onDelete={() => void remove(svc)}
              onError={setError}
            />
          ))}
        </ul>
      ) : (
        <p className="rounded-xl border border-dashed border-slate-300 px-4 py-6 text-center text-sm text-slate-500">
          עדיין אין שירותים. הוסיפו את השירות הראשון למטה.
        </p>
      )}

      {/* Add new */}
      <form
        onSubmit={(ev) => void add(ev)}
        className="flex flex-col gap-3 rounded-xl border border-black/10 bg-white p-3"
      >
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[12rem] flex-1">
            <Field
              label="שם השירות"
              value={newName}
              onChange={(ev) => setNewName(ev.target.value)}
              placeholder="לדוגמה: ייעוץ ראשוני"
              maxLength={120}
            />
          </div>
          <div className="w-32">
            <Field
              label="משך (דקות)"
              type="number"
              min={5}
              max={1440}
              step={5}
              value={newDuration}
              onChange={(ev) => setNewDuration(ev.target.value)}
            />
          </div>
          <div className="w-32">
            <Field
              label="מחיר ₪ (לא חובה)"
              type="number"
              min={0}
              step={1}
              inputMode="numeric"
              value={newPrice}
              onChange={(ev) => setNewPrice(ev.target.value)}
              placeholder="ללא עלות"
            />
          </div>
        </div>
        <Textarea
          label="תיאור (לא חובה)"
          value={newDescription}
          onChange={(ev) => setNewDescription(ev.target.value)}
          rows={2}
          maxLength={500}
          placeholder="מה כולל השירות?"
        />
        <div>
          <Button type="submit" disabled={adding} className="!bg-leaf hover:!bg-leaf-dark">
            <Icon name="plus" size={16} />
            {adding ? 'מוסיף…' : 'הוסף שירות'}
          </Button>
        </div>
      </form>
    </div>
  )
}

// One editable service row. Local draft state so typing doesn't refetch; "שמור"
// commits and only enables when something actually changed.
function ServiceRow({
  service,
  busy,
  onSave,
  onToggleActive,
  onDelete,
  onError,
}: {
  service: ServiceItem
  busy: boolean
  onSave: (body: ServiceUpdate) => void
  onToggleActive: () => void
  onDelete: () => void
  onError: (msg: string) => void
}) {
  const [name, setName] = useState(service.name)
  const [duration, setDuration] = useState(String(service.duration_minutes))
  const [description, setDescription] = useState(service.description ?? '')
  const [price, setPrice] = useState(service.price == null ? '' : String(service.price))

  const dur = Number(duration)
  const parsedPrice = parsePrice(price)
  const currentDesc = service.description ?? ''

  const dirty =
    name.trim() !== service.name ||
    (Number.isFinite(dur) && dur > 0 && dur !== service.duration_minutes) ||
    description.trim() !== currentDesc ||
    (parsedPrice !== undefined && parsedPrice !== service.price)
  const valid =
    name.trim().length > 0 &&
    Number.isFinite(dur) &&
    dur > 0 &&
    parsedPrice !== undefined

  function save() {
    if (parsedPrice === undefined) {
      onError('המחיר חייב להיות מספר שלם אי-שלילי (₪).')
      return
    }
    // Only send fields that actually changed (null clears description/price).
    const body: ServiceUpdate = {}
    if (name.trim() !== service.name) body.name = name.trim()
    if (dur !== service.duration_minutes) body.duration_minutes = dur
    if (description.trim() !== currentDesc) body.description = description.trim() || null
    if (parsedPrice !== service.price) body.price = parsedPrice
    onSave(body)
  }

  return (
    <li className="flex flex-col gap-3 rounded-xl border border-black/10 bg-white p-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[12rem] flex-1">
          <Field
            label="שם השירות"
            value={name}
            onChange={(ev) => setName(ev.target.value)}
            maxLength={120}
            disabled={busy}
          />
        </div>
        <div className="w-28">
          <Field
            label="משך (דקות)"
            type="number"
            min={5}
            max={1440}
            step={5}
            value={duration}
            onChange={(ev) => setDuration(ev.target.value)}
            disabled={busy}
          />
        </div>
        <div className="w-28">
          <Field
            label="מחיר ₪"
            type="number"
            min={0}
            step={1}
            inputMode="numeric"
            value={price}
            onChange={(ev) => setPrice(ev.target.value)}
            placeholder="ללא עלות"
            disabled={busy}
          />
        </div>

        <label className="flex items-center gap-2 pb-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={service.active}
            onChange={onToggleActive}
            disabled={busy}
            className="h-4 w-4 rounded border-slate-300 text-leaf focus-visible:ring-leaf"
          />
          פעיל
        </label>
      </div>

      <Textarea
        label="תיאור"
        value={description}
        onChange={(ev) => setDescription(ev.target.value)}
        rows={2}
        maxLength={500}
        placeholder="מה כולל השירות?"
        disabled={busy}
      />

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={save}
          disabled={busy || !dirty || !valid}
          className="inline-flex items-center gap-1.5 rounded-lg border border-leaf px-3 py-1.5 text-sm font-medium text-leaf-ink transition hover:bg-leaf-soft disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Icon name="device-floppy" size={16} />
          {busy ? 'שומר…' : 'שמור'}
        </button>

        <button
          type="button"
          onClick={onDelete}
          disabled={busy}
          aria-label={`מחק את השירות ${service.name}`}
          className="rounded-lg p-2 text-slate-400 transition hover:bg-red-50 hover:text-bad disabled:opacity-50"
        >
          <Icon name="trash" size={18} />
        </button>
      </div>
    </li>
  )
}
