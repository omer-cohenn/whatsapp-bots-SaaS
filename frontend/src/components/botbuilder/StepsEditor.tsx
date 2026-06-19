// Edits the steps of the active flow as an ACCORDION: each step shows a compact
// header (number + a one-line summary); clicking it expands that step for editing
// and collapses the others. The shape per step matches the backend contract
// (key/question/type/required/options); the server re-validates on PUT, so here
// we focus on clear editing + light inline guidance.

import { useState } from 'react'
import type { Flow, Step, StepType } from '../../botbuilder/types'
import { emptyStep, uniqueKey } from '../../botbuilder/config'
import { MAX_CHOICE_OPTIONS, MAX_STEPS_PER_FLOW, MIN_CHOICE_OPTIONS } from '../../botbuilder/types'
import Button from '../ui/Button'
import Field from '../ui/Field'
import Select, { type SelectOption } from '../ui/Select'
import Icon from '../ui/Icon'

const STEP_TYPE_OPTIONS: SelectOption[] = [
  { value: 'text', label: 'טקסט חופשי' },
  { value: 'phone', label: 'טלפון' },
  { value: 'email', label: 'אימייל' },
  { value: 'choice', label: 'בחירה מרשימה' },
]

type Props = {
  flow: Flow
  /** Replace the active flow's steps with `next`. */
  onStepsChange: (next: Step[]) => void
}

export default function StepsEditor({ flow, onStepsChange }: Props) {
  // Accordion: index of the expanded step (-1 = all collapsed). Start with the
  // first step open so the editor isn't empty on load.
  const [openIndex, setOpenIndex] = useState<number>(flow.steps.length > 0 ? 0 : -1)

  // human_handoff collects nothing — its customer message is edited by the parent.
  if (flow.flow_type === 'human_handoff') return null

  function updateStep(index: number, patch: Partial<Step>) {
    onStepsChange(flow.steps.map((s, i) => (i === index ? { ...s, ...patch } : s)))
  }

  function changeType(index: number, type: StepType) {
    // Switching to/from "choice" toggles the options array on/off.
    const step = flow.steps[index]
    const next: Partial<Step> =
      type === 'choice'
        ? { type, options: step.options && step.options.length >= 2 ? step.options : ['', ''] }
        : { type, options: null }
    updateStep(index, next)
  }

  function addStep() {
    const base = emptyStep()
    // Keep the example field id unique within the flow (שם_מלא, שם_מלא_2, …).
    const step = { ...base, key: uniqueKey(base.key, flow.steps.map((s) => s.key)) }
    const next = [...flow.steps, step]
    onStepsChange(next)
    setOpenIndex(next.length - 1) // open the freshly added step for editing
  }

  function removeStep(index: number) {
    onStepsChange(flow.steps.filter((_, i) => i !== index))
    // Keep the accordion sensible after removal.
    setOpenIndex((cur) => (cur === index ? -1 : cur > index ? cur - 1 : cur))
  }

  function updateOption(stepIndex: number, optIndex: number, value: string) {
    const step = flow.steps[stepIndex]
    const opts = [...(step.options ?? [])]
    opts[optIndex] = value
    updateStep(stepIndex, { options: opts })
  }

  function addOption(stepIndex: number) {
    const step = flow.steps[stepIndex]
    const opts = [...(step.options ?? []), '']
    updateStep(stepIndex, { options: opts })
  }

  function removeOption(stepIndex: number, optIndex: number) {
    const step = flow.steps[stepIndex]
    const opts = (step.options ?? []).filter((_, i) => i !== optIndex)
    updateStep(stepIndex, { options: opts })
  }

  const atMax = flow.steps.length >= MAX_STEPS_PER_FLOW

  return (
    <div className="flex flex-col gap-3">
      <ol className="flex flex-col gap-2.5">
        {flow.steps.map((step, index) => {
          const open = openIndex === index
          const summary = step.question.trim() || step.key.trim() || 'שלב חדש'
          return (
            <li key={index} className="overflow-hidden rounded-xl border border-slate-200 bg-white">
              {/* Accordion header — click to expand/collapse this step. */}
              <div className="flex items-center gap-1 px-2 py-2">
                <button
                  type="button"
                  onClick={() => setOpenIndex(open ? -1 : index)}
                  aria-expanded={open}
                  aria-controls={`step-body-${index}`}
                  className="flex flex-1 items-center gap-2.5 rounded-lg px-2 py-1.5 text-right hover:bg-slate-50"
                >
                  <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-leaf-soft text-xs text-leaf-ink">
                    {index + 1}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-800">
                    {summary}
                  </span>
                  <Icon
                    name="chevron-down"
                    size={18}
                    className={`flex-shrink-0 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`}
                  />
                </button>
                <Button
                  variant="ghost"
                  onClick={() => removeStep(index)}
                  aria-label={`מחק שלב ${index + 1}`}
                  className="flex-shrink-0 px-2 py-1 text-bad hover:bg-red-50"
                >
                  <Icon name="trash" size={16} />
                </Button>
              </div>

              {/* Accordion body — the step editor (only when expanded). */}
              {open ? (
                <div id={`step-body-${index}`} className="border-t border-slate-100 px-4 pb-4 pt-3">
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field
                      label="מזהה השדה"
                      hint="אותיות (עברית/אנגלית), מספרים, רווח או קו תחתון"
                      value={step.key}
                      placeholder="שם_מלא"
                      onChange={(e) => updateStep(index, { key: e.target.value })}
                    />
                    <Select
                      label="סוג השדה"
                      options={STEP_TYPE_OPTIONS}
                      value={step.type}
                      onChange={(e) => changeType(index, e.target.value as StepType)}
                    />
                  </div>

                  <div className="mt-3">
                    <Field
                      label="השאלה ללקוח"
                      value={step.question}
                      placeholder="מה השם המלא שלך?"
                      onChange={(e) => updateStep(index, { question: e.target.value })}
                    />
                  </div>

                  {step.type === 'choice' ? (
                    <fieldset className="mt-3">
                      <legend className="mb-1.5 text-sm font-medium text-slate-800">
                        אפשרויות בחירה
                      </legend>
                      <p className="mb-2 text-xs text-slate-500">
                        בין {MIN_CHOICE_OPTIONS} ל-{MAX_CHOICE_OPTIONS} אפשרויות.
                      </p>
                      <div className="flex flex-col gap-2">
                        {(step.options ?? []).map((opt, optIndex) => (
                          <div key={optIndex} className="flex items-center gap-2">
                            <Field
                              label={`אפשרות ${optIndex + 1}`}
                              className="flex-1"
                              value={opt}
                              onChange={(e) => updateOption(index, optIndex, e.target.value)}
                            />
                            <Button
                              variant="ghost"
                              onClick={() => removeOption(index, optIndex)}
                              aria-label={`מחק אפשרות ${optIndex + 1}`}
                              className="mt-6 px-2 py-1 text-bad hover:bg-red-50"
                            >
                              <Icon name="x" size={16} />
                            </Button>
                          </div>
                        ))}
                      </div>
                      {(step.options ?? []).length < MAX_CHOICE_OPTIONS ? (
                        <Button variant="secondary" onClick={() => addOption(index)} className="mt-2">
                          <Icon name="plus" size={15} />
                          הוסף אפשרות
                        </Button>
                      ) : null}
                    </fieldset>
                  ) : null}

                  <label className="mt-3 flex items-center gap-2 text-sm text-slate-700">
                    <input
                      type="checkbox"
                      checked={step.required}
                      onChange={(e) => updateStep(index, { required: e.target.checked })}
                      className="h-4 w-4 rounded border-slate-300 text-leaf focus:ring-leaf"
                    />
                    שדה חובה
                  </label>
                </div>
              ) : null}
            </li>
          )
        })}
      </ol>

      {flow.steps.length === 0 ? (
        <p className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-6 text-center text-sm text-slate-500">
          {flow.flow_type === 'lead'
            ? 'מסלול איסוף ליד חייב לפחות שלב אחד. הוסיפו שלב כדי להתחיל.'
            : 'אין שלבים עדיין. הוסיפו שלב כדי להתחיל.'}
        </p>
      ) : null}

      <Button
        variant="secondary"
        onClick={addStep}
        disabled={atMax}
        className="justify-center border border-dashed border-slate-300 bg-transparent"
      >
        <Icon name="plus" size={15} />
        {atMax ? `הגעת למקסימום (${MAX_STEPS_PER_FLOW})` : 'הוסף שלב'}
      </Button>
    </div>
  )
}
