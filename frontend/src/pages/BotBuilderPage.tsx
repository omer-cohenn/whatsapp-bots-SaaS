// The AI bot builder (M4). Loads the tenant's bot config, lets the owner edit
// flows (tabs + type selector + steps) and the minimal bot profile, and saves
// via PUT /api/bot/settings. The "עוזר ה-AI שלך" button opens a chat panel that
// can apply validated config changes to this page's in-memory state live.
//
// The SERVER is the validation gate: PUT answers 422 on any contract violation,
// which we surface as a friendly message. We mirror a few bounds here only for
// nicer UX (e.g. required name/prompt), never as the source of truth. The tenant
// (business_id) is always derived server-side — never sent from here.

import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import DashboardLayout from '../components/DashboardLayout'
import FlowTabs from '../components/botbuilder/FlowTabs'
import FlowTypeSelector from '../components/botbuilder/FlowTypeSelector'
import StepsEditor from '../components/botbuilder/StepsEditor'
import AIChatPanel from '../components/botbuilder/AIChatPanel'
import Button from '../components/ui/Button'
import Field from '../components/ui/Field'
import Textarea from '../components/ui/Textarea'
import Spinner from '../components/ui/Spinner'
import Alert from '../components/ui/Alert'
import Icon from '../components/ui/Icon'
import Badge from '../components/ui/Badge'
import PublishToggle from '../components/dashboard/PublishToggle'
import { getSettings, saveSettings } from '../lib/botClient'
import { ApiError } from '../lib/apiClient'
import type { BotSettings, Flow, FlowType, Step } from '../botbuilder/types'
import {
  DEFAULT_BOOKING_MESSAGE,
  DEFAULT_HANDOFF_MESSAGE,
  emptyFlow,
  normalizeSettings,
  uniqueKey,
} from '../botbuilder/config'

// Map a 422 validation error (Pydantic detail) to a readable Hebrew message.
function describeSaveError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 422) {
      return 'חלק מהשדות אינם תקינים. ודאו שלבוט יש שם והנחיה, שלכל מסלול איסוף יש לפחות שלב אחד, ושלכל שלב "בחירה" יש לפחות שתי אפשרויות.'
    }
    if (err.status === 401) return 'פג תוקף ההתחברות. רעננו את העמוד והתחברו מחדש.'
    if (err.status === 0) return 'אין חיבור לשרת. בדקו את החיבור ונסו שוב.'
  }
  return 'שמירת ההגדרות נכשלה. נסו שוב.'
}

// Human-readable label per flow type (shown read-only until the owner clicks the
// pencil to change it).
const FLOW_TYPE_LABELS: Record<FlowType, string> = {
  lead: 'איסוף ליד',
  human_handoff: 'מעבר לנציג',
  booking: 'קביעת פגישה',
}

export default function BotBuilderPage() {
  const [config, setConfig] = useState<BotSettings | null>(null)
  const [activeKey, setActiveKey] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [aiOpen, setAiOpen] = useState(false)
  // Flow type is read-only until the owner clicks the pencil (per-tab).
  const [editingType, setEditingType] = useState(false)

  // Load the current config on mount.
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadError(null)
    getSettings()
      .then((raw) => {
        if (cancelled) return
        const normalized = normalizeSettings(raw)
        setConfig(normalized)
        const firstKey = Object.keys(normalized.lead_steps)[0] ?? null
        setActiveKey(firstKey)
      })
      .catch((err) => {
        if (cancelled) return
        setLoadError(
          err instanceof ApiError && err.status === 401
            ? 'פג תוקף ההתחברות. רעננו את העמוד.'
            : 'טעינת הגדרות הבוט נכשלה. רעננו את העמוד ונסו שוב.',
        )
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Collapse the flow-type editor whenever the active tab changes.
  useEffect(() => {
    setEditingType(false)
  }, [activeKey])

  // --- config mutators (all keep the working copy well-formed) ---------------

  // Clear the "saved" flag whenever the config changes after a save.
  const mutate = useCallback((next: BotSettings) => {
    setConfig(next)
    setSaved(false)
  }, [])

  function setProfile(patch: Partial<BotSettings['bot_profile']>) {
    if (!config) return
    mutate({ ...config, bot_profile: { ...config.bot_profile, ...patch } })
  }

  function addFlow() {
    if (!config) return
    const existing = Object.keys(config.lead_steps)
    const key = uniqueKey('flow', existing)
    const nextFlows = { ...config.lead_steps, [key]: emptyFlow('מסלול חדש', 'lead') }
    mutate({ ...config, lead_steps: nextFlows })
    setActiveKey(key)
  }

  function deleteFlow(key: string) {
    if (!config) return
    const nextFlows = { ...config.lead_steps }
    delete nextFlows[key]
    mutate({ ...config, lead_steps: nextFlows })
    // Move selection to a neighbour.
    const remaining = Object.keys(nextFlows)
    setActiveKey(remaining[0] ?? null)
  }

  function renameFlowLabel(key: string, label: string) {
    if (!config) return
    const flow = config.lead_steps[key]
    if (!flow) return
    mutate({
      ...config,
      lead_steps: { ...config.lead_steps, [key]: { ...flow, label } },
    })
  }

  function patchActiveFlow(patch: Partial<Flow>) {
    if (!config || !activeKey) return
    const flow = config.lead_steps[activeKey]
    if (!flow) return
    mutate({
      ...config,
      lead_steps: { ...config.lead_steps, [activeKey]: { ...flow, ...patch } },
    })
  }

  function changeActiveFlowType(flowType: FlowType) {
    if (!config || !activeKey) return
    const flow = config.lead_steps[activeKey]
    if (!flow) return
    // Switching type adjusts steps to stay contract-valid:
    //   human_handoff → no steps; lead → at least one; booking keeps steps.
    let steps = flow.steps
    if (flowType === 'human_handoff') steps = []
    else if (flowType === 'lead' && steps.length === 0) steps = emptyFlow('', 'lead').steps
    const serviceName = flowType === 'booking' ? (flow.service_name ?? '') : null
    // Seed the right default customer-facing message for the message-based types
    // — and swap a default left over from the previous type so the field always
    // shows the correct real message (the owner can still edit it).
    let message = flow.message ?? null
    if (flowType === 'human_handoff') {
      message = !message?.trim() || message === DEFAULT_BOOKING_MESSAGE ? DEFAULT_HANDOFF_MESSAGE : message
    } else if (flowType === 'booking') {
      message = !message?.trim() || message === DEFAULT_HANDOFF_MESSAGE ? DEFAULT_BOOKING_MESSAGE : message
    }
    patchActiveFlow({ flow_type: flowType, steps, service_name: serviceName, message })
  }

  function setActiveFlowSteps(steps: Step[]) {
    patchActiveFlow({ steps })
  }

  // Apply a validated config change coming from the AI panel, live.
  const applyAiChanges = useCallback((next: BotSettings) => {
    const normalized = normalizeSettings(next)
    setConfig(normalized)
    setSaved(false)
    // Keep the current tab if it still exists; else select the first flow.
    setActiveKey((prev) => {
      if (prev && normalized.lead_steps[prev]) return prev
      return Object.keys(normalized.lead_steps)[0] ?? null
    })
  }, [])

  // --- save -------------------------------------------------------------------

  async function onSave() {
    if (!config) return
    setSaving(true)
    setSaveError(null)
    setSaved(false)
    try {
      // The server normalizes (e.g. snake_cases nothing — keys are already keys)
      // and returns the saved shape; adopt it so local state matches the DB.
      const savedCfg = await saveSettings(config)
      setConfig(normalizeSettings(savedCfg))
      setSaved(true)
    } catch (err) {
      setSaveError(describeSaveError(err))
    } finally {
      setSaving(false)
    }
  }

  const activeFlow = config && activeKey ? config.lead_steps[activeKey] : undefined

  return (
    <DashboardLayout>
      <div className="mx-auto w-full max-w-4xl px-4 py-6 sm:px-6">
        {/* Builder header: title + AI + save.
            The four actions add up to ~396px, which does NOT fit the 358px a
            390px phone leaves after the gutter. The action cluster therefore
            wraps (flex-wrap) and takes the full row below the title on phones,
            so the buttons reflow onto two lines instead of overflowing the page
            sideways. From sm it goes back to a single inline row beside the
            title, exactly as before. */}
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <h1 className="text-2xl font-bold text-slate-900">בונה הבוט</h1>
          <div className="flex w-full flex-wrap items-center justify-end gap-2 sm:w-auto">
            {config ? (
              // Go-live: PUT /api/bot/publish persists immediately (independent of
              // the "שמור שינויים" config save), so we update is_published in place
              // without flipping the unsaved-changes flag.
              <PublishToggle
                isPublished={config.is_published}
                onChange={(next) =>
                  setConfig((prev) => (prev ? { ...prev, is_published: next } : prev))
                }
              />
            ) : null}
            <Link
              to="/try-me"
              className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-800 transition hover:bg-slate-200 sm:min-h-0"
            >
              <Icon name="player-play" size={16} />
              נסה אותי
            </Link>
            <Button
              variant="primary"
              onClick={() => setAiOpen(true)}
              className="min-h-[44px] !bg-leaf text-white hover:!bg-leaf-dark sm:min-h-0"
            >
              <Icon name="sparkles" size={17} />
              עוזר ה-AI שלך
            </Button>
            <Button
              onClick={() => void onSave()}
              disabled={saving || loading || !config}
              className="min-h-[44px] sm:min-h-0"
            >
              <Icon name="device-floppy" size={16} />
              {saving ? 'שומר…' : 'שמור שינויים'}
            </Button>
          </div>
        </div>

        {loading ? (
          <Spinner label="טוען את הגדרות הבוט…" className="py-16" />
        ) : loadError ? (
          <Alert tone="error">{loadError}</Alert>
        ) : config ? (
          <div className="flex flex-col gap-5">
            {/* Save feedback (announced via Alert's live region). */}
            {saveError ? <Alert tone="error">{saveError}</Alert> : null}
            {saved ? <Alert tone="info">ההגדרות נשמרו בהצלחה.</Alert> : null}

            {/* Bot profile (name + prompt are required to save). */}
            <section
              aria-labelledby="bot-profile-heading"
              className="rounded-2xl border border-slate-200 bg-white p-5"
            >
              <h2
                id="bot-profile-heading"
                className="mb-4 flex items-center gap-2 text-base font-medium text-slate-900"
              >
                <Icon name="robot" size={18} className="text-leaf" />
                פרטי הבוט
              </h2>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field
                  label="שם הבוט"
                  value={config.bot_profile.name ?? ''}
                  placeholder="לדוגמה: העוזר של דמו ביטוח"
                  onChange={(e) => setProfile({ name: e.target.value })}
                />
                <Field
                  label="טון (לא חובה)"
                  value={config.bot_profile.tone ?? ''}
                  placeholder="מקצועי וחם"
                  onChange={(e) => setProfile({ tone: e.target.value })}
                />
              </div>
              <div className="mt-4">
                <Textarea
                  label="הנחיית מערכת (System Prompt)"
                  hint="הסבירו לבוט מי הוא ואיך לענות. אל תכניסו כאן סודות או מפתחות."
                  rows={4}
                  value={config.bot_profile.system_prompt ?? ''}
                  placeholder="אתה עוזר של סוכנות ביטוח. ענה בקצרה והובל את הלקוח להשאיר פרטים."
                  onChange={(e) => setProfile({ system_prompt: e.target.value })}
                />
              </div>
            </section>

            {/* Flows */}
            <section aria-labelledby="flows-heading" className="flex flex-col gap-4">
              <div className="flex items-center justify-between gap-2">
                <h2 id="flows-heading" className="text-base font-medium text-slate-900">
                  מסלולי שיחה
                </h2>
                <Badge tone="neutral">{Object.keys(config.lead_steps).length} מסלולים</Badge>
              </div>

              <FlowTabs
                flows={config.lead_steps}
                activeKey={activeKey}
                onSelect={setActiveKey}
                onAdd={addFlow}
                onRenameLabel={renameFlowLabel}
                onDelete={deleteFlow}
              />

              {activeFlow && activeKey ? (
                <div
                  role="tabpanel"
                  id={`tabpanel-${activeKey}`}
                  aria-labelledby={`tab-${activeKey}`}
                  className="flex flex-col gap-4"
                >
                  {editingType ? (
                    <FlowTypeSelector
                      value={activeFlow.flow_type}
                      onChange={(t) => {
                        changeActiveFlowType(t)
                        setEditingType(false)
                      }}
                    />
                  ) : (
                    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3">
                      <span className="text-sm font-medium text-slate-800">סוג המסלול</span>
                      <Badge tone="leaf">{FLOW_TYPE_LABELS[activeFlow.flow_type]}</Badge>
                      <Button
                        variant="ghost"
                        onClick={() => setEditingType(true)}
                        aria-label="שינוי סוג המסלול"
                        className="ms-auto min-h-[44px] min-w-[44px] px-2 py-1 text-slate-500 hover:text-leaf sm:min-h-0 sm:min-w-0"
                      >
                        <Icon name="pencil" size={16} />
                      </Button>
                    </div>
                  )}

                  {activeFlow.flow_type === 'human_handoff' ? (
                    <Textarea
                      label="הודעת מעבר ללקוח"
                      hint="ההודעה שתישלח ללקוח כשהשיחה עוברת לנציג אנושי."
                      rows={3}
                      value={activeFlow.message ?? ''}
                      placeholder={DEFAULT_HANDOFF_MESSAGE}
                      onChange={(e) => patchActiveFlow({ message: e.target.value })}
                    />
                  ) : null}

                  {activeFlow.flow_type === 'booking' ? (
                    <>
                      <Field
                        label="שם השירות"
                        hint="יוצג ללקוח בקביעת התור"
                        value={activeFlow.service_name ?? ''}
                        placeholder="פגישת ייעוץ"
                        onChange={(e) => patchActiveFlow({ service_name: e.target.value })}
                      />
                      <Textarea
                        label="הודעה ללקוח"
                        hint="השתמשו ב-{link} למיקום הקישור לקביעת התור."
                        rows={3}
                        value={activeFlow.message ?? ''}
                        placeholder={DEFAULT_BOOKING_MESSAGE}
                        onChange={(e) => patchActiveFlow({ message: e.target.value })}
                      />
                    </>
                  ) : null}

                  {activeFlow.flow_type !== 'human_handoff' ? (
                    // key={activeKey} remounts the accordion per flow so its
                    // open/closed state resets cleanly when switching tabs.
                    <StepsEditor key={activeKey} flow={activeFlow} onStepsChange={setActiveFlowSteps} />
                  ) : null}
                </div>
              ) : (
                <p className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-10 text-center text-sm text-slate-500">
                  עדיין אין מסלולים. לחצו על "מסלול חדש" כדי להתחיל, או בקשו מעוזר ה-AI לבנות
                  עבורכם.
                </p>
              )}
            </section>
          </div>
        ) : null}
      </div>

      {/* AI assistant half-window. config is guaranteed non-null when openable. */}
      {config ? (
        <AIChatPanel
          open={aiOpen}
          onClose={() => setAiOpen(false)}
          config={config}
          onApplyChanges={applyAiChanges}
        />
      ) : null}
    </DashboardLayout>
  )
}
