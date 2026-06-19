// The flow tab strip: one tab per flow (tab label = the flow's display name),
// plus a "מסלול חדש" button at the LEFT end (RTL → visually leftmost). Editing
// the active flow's name and deleting it live in a small toolbar under the strip
// (clearer + more accessible than cramming controls inside a tab).
//
// ARIA: the strip is a role="tablist" (see ui/Tabs); the editor panel below is
// the matching role="tabpanel" (wired by BotBuilderPage). Keyboard arrows move
// between tabs via the shared Tabs primitive.

import { useEffect, useRef, useState } from 'react'
import type { Flow } from '../../botbuilder/types'
import { MAX_FLOWS } from '../../botbuilder/types'
import Tabs, { type TabItem } from '../ui/Tabs'
import Button from '../ui/Button'
import Icon from '../ui/Icon'

type Props = {
  flows: Record<string, Flow>
  activeKey: string | null
  onSelect: (key: string) => void
  onAdd: () => void
  onRenameLabel: (key: string, label: string) => void
  onDelete: (key: string) => void
}

export default function FlowTabs({
  flows,
  activeKey,
  onSelect,
  onAdd,
  onRenameLabel,
  onDelete,
}: Props) {
  const entries = Object.entries(flows)
  const items: TabItem[] = entries.map(([key, flow]) => ({
    id: key,
    label: flow.label || '(ללא שם)',
  }))
  const activeFlow = activeKey ? flows[activeKey] : undefined
  const atMax = entries.length >= MAX_FLOWS

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200">
        {items.length > 0 && activeKey ? (
          <Tabs items={items} activeId={activeKey} onChange={onSelect} label="מסלולים" />
        ) : (
          <span className="px-1 py-2 text-sm text-slate-500">אין מסלולים עדיין</span>
        )}
        {/* "מסלול חדש" at the left end of the strip (RTL: appears leftmost). */}
        <Button
          variant="secondary"
          onClick={onAdd}
          disabled={atMax}
          className="mr-auto bg-leaf-soft text-leaf-ink hover:bg-leaf-soft/80"
        >
          <Icon name="plus" size={15} />
          {atMax ? `מקסימום ${MAX_FLOWS} מסלולים` : 'מסלול חדש'}
        </Button>
      </div>

      {activeFlow && activeKey ? (
        <FlowToolbar
          flowKey={activeKey}
          label={activeFlow.label}
          onRenameLabel={onRenameLabel}
          onDelete={onDelete}
        />
      ) : null}
    </div>
  )
}

// Rename + delete controls for the currently-active flow. The name field is the
// single source of the tab's display label; editing it updates the tab live.
function FlowToolbar({
  flowKey,
  label,
  onRenameLabel,
  onDelete,
}: {
  flowKey: string
  label: string
  onRenameLabel: (key: string, label: string) => void
  onDelete: (key: string) => void
}) {
  const [confirming, setConfirming] = useState(false)
  // Reset the confirm prompt whenever the active flow changes.
  const prevKey = useRef(flowKey)
  useEffect(() => {
    if (prevKey.current !== flowKey) {
      prevKey.current = flowKey
      setConfirming(false)
    }
  }, [flowKey])

  return (
    <div className="flex flex-wrap items-end gap-3">
      <div className="flex flex-col gap-1.5">
        <label
          htmlFor={`flow-name-${flowKey}`}
          className="flex items-center gap-1.5 text-sm font-medium text-slate-800"
        >
          <Icon name="pencil" size={15} className="text-slate-500" />
          שם המסלול
        </label>
        <input
          id={`flow-name-${flowKey}`}
          value={label}
          onChange={(e) => onRenameLabel(flowKey, e.target.value)}
          placeholder="לדוגמה: ביטוח רכב"
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400"
        />
      </div>

      {confirming ? (
        <div className="flex items-center gap-2" role="group" aria-label="אישור מחיקת מסלול">
          <span className="text-sm text-slate-600">למחוק את המסלול?</span>
          <Button
            variant="secondary"
            onClick={() => {
              onDelete(flowKey)
              setConfirming(false)
            }}
            className="text-bad"
          >
            כן, מחק
          </Button>
          <Button variant="ghost" onClick={() => setConfirming(false)}>
            ביטול
          </Button>
        </div>
      ) : (
        <Button
          variant="ghost"
          onClick={() => setConfirming(true)}
          className="text-bad hover:bg-red-50"
        >
          <Icon name="trash" size={16} />
          מחק מסלול
        </Button>
      )}
    </div>
  )
}
