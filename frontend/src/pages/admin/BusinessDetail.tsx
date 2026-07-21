// One business's profile in the back-office (M12, route /admin/businesses/:id).
// Three blocks: a header (name + owner + status + key facts), a subscription
// control panel (change plan/status → silences or re-enables the bot), and the
// usage charts section. 404 (unknown business) and load errors get a friendly
// Hebrew state. Admin-gated server-side; deliberate cross-tenant view.

import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import DashboardLayout from '../../components/DashboardLayout'
import Card from '../../components/ui/Card'
import Spinner from '../../components/ui/Spinner'
import Alert from '../../components/ui/Alert'
import Icon from '../../components/ui/Icon'
import StatusBadge from '../../components/admin/StatusBadge'
import SubscriptionPanel from '../../components/admin/SubscriptionPanel'
import UsageSection from '../../components/admin/UsageSection'
import CrmPanel from '../../components/admin/CrmPanel'
import Modal from '../../components/ui/Modal'
import { getBusiness, getPlans, deleteBusiness } from '../../lib/adminClient'
import { ApiError } from '../../lib/apiClient'
import { toFriendlyError } from '../../lib/friendlyError'
import { formatPrice, formatMoney } from '../../admin/labels'
import { fullDateTime } from '../../lib/formatDate'
import type {
  BusinessCrmSummary,
  BusinessDetail as BusinessDetailType,
  CrmStage,
  Plan,
} from '../../admin/types'

// One labelled fact in the header grid; null values show an em-dash.
function Fact({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="text-sm font-medium text-slate-900">{value || '—'}</dd>
    </div>
  )
}

export default function BusinessDetail() {
  const { id = '' } = useParams<{ id: string }>()

  const navigate = useNavigate()
  const [business, setBusiness] = useState<BusinessDetailType | null>(null)
  const [plans, setPlans] = useState<Plan[]>([])
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Danger zone — the permanent-delete confirmation flow.
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const load = useCallback(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setNotFound(false)
    Promise.all([getBusiness(id), getPlans()])
      .then(([detail, planRes]) => {
        if (cancelled) return
        setBusiness(detail)
        setPlans(planRes.plans)
      })
      .catch((err) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 404) {
          setNotFound(true)
        } else {
          setError(toFriendlyError(err, 'טעינת פרטי העסק נכשלה. נסו שוב.'))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [id])

  useEffect(() => load(), [load])

  // After a successful subscription save, patch the local header optimistically.
  const handleSaved = useCallback(
    (planCode: string, status: BusinessDetailType['status'], isActive: boolean) => {
      setBusiness((prev) =>
        prev ? { ...prev, plan_code: planCode, status, is_active: isActive } : prev,
      )
    },
    [],
  )

  // After a CRM stage/follow-up save, reflect it in the local crm summary.
  const handleCrmChanged = useCallback(
    (stage: CrmStage, nextFollowupAt: string | null) => {
      setBusiness((prev) => {
        if (!prev) return prev
        const base: BusinessCrmSummary = prev.crm ?? {
          stage,
          last_contacted_at: null,
          next_followup_at: nextFollowupAt,
        }
        return {
          ...prev,
          crm: { ...base, stage, next_followup_at: nextFollowupAt },
        }
      })
    },
    [],
  )

  // Permanent delete: wipe the business (cascade) then return to the list. A 400
  // means the admin tried to delete their OWN session business (server guard).
  const handleDelete = useCallback(async () => {
    if (!business) return
    setDeleting(true)
    setDeleteError(null)
    try {
      await deleteBusiness(business.business_id)
      navigate('/admin/businesses', { replace: true })
    } catch (err) {
      setDeleteError(
        err instanceof ApiError && err.status === 400
          ? 'אי אפשר למחוק את העסק שמקושר לחשבון שלך.'
          : toFriendlyError(err, 'מחיקת העסק נכשלה. נסו שוב.'),
      )
      setDeleting(false)
    }
  }, [business, navigate])

  // The current plan's display name for the header fact.
  const planLabel = business
    ? (() => {
        const plan = plans.find((p) => p.code === business.plan_code)
        if (!plan) return business.plan_code
        return `${plan.name || plan.code} · ${formatPrice(plan.price)}`
      })()
    : ''

  return (
    <DashboardLayout>
      {/* gutter של העמוד עצמו — המעטפת לא מרפדת את <main>. */}
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 py-6 sm:px-6 sm:py-10">
        <Link
          to="/admin/businesses"
          className="inline-flex min-h-11 w-fit items-center gap-1 rounded text-sm font-medium text-leaf-ink sm:min-h-0 underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-leaf focus-visible:ring-offset-2"
        >
          <Icon name="chevron-right" size={16} />
          חזרה לרשימת העסקים
        </Link>

        {loading ? (
          <Spinner label="טוען פרטי עסק…" className="py-16" />
        ) : notFound ? (
          <Alert tone="warning">העסק המבוקש לא נמצא. ייתכן שהוסר.</Alert>
        ) : error ? (
          <Alert tone="error">{error}</Alert>
        ) : business ? (
          <>
            {/* Header */}
            <Card>
              <div className="flex flex-wrap items-start justify-between gap-3">
                {/* min-w-0 + break-words: שם עסק או אימייל ארוכים לא ידחפו
                    את הכרטיס מעבר לרוחב המסך. */}
                <div className="min-w-0 flex-1">
                  <h1 className="flex items-start gap-2 text-xl font-bold text-slate-900 sm:text-2xl">
                    <Icon
                      name="building-store"
                      size={24}
                      className="mt-0.5 shrink-0 text-leaf"
                    />
                    <span className="min-w-0 break-words">
                      {business.name || 'עסק ללא שם'}
                    </span>
                  </h1>
                  {business.owner_email ? (
                    <p className="mt-1 flex items-start gap-1.5 text-sm text-slate-600">
                      <Icon name="mail" size={15} className="mt-0.5 shrink-0" />
                      <span className="min-w-0 break-all">{business.owner_email}</span>
                    </p>
                  ) : null}
                </div>
                <span className="shrink-0">
                  <StatusBadge status={business.status} />
                </span>
              </div>

              <dl className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-3">
                <Fact label="סוג עסק" value={business.business_type} />
                <Fact label="מנוי" value={planLabel} />
                <Fact label="חיבור וואטסאפ" value={business.wa_status} />
                <Fact
                  label="נרשם"
                  value={business.created_at ? fullDateTime(business.created_at) : null}
                />
                <Fact
                  label="כניסה אחרונה"
                  value={
                    business.last_login_at ? fullDateTime(business.last_login_at) : null
                  }
                />
                {/* שני נתונים בתא אחד — ב-390px gap-6 היה דוחס אותם, gap-4 נושם. */}
                <div className="flex gap-4 sm:gap-6">
                  <Fact label="לידים" value={String(business.leads_count)} />
                  <Fact label="הודעות (30 ימים)" value={String(business.msgs_30d)} />
                </div>
                <Fact
                  label="LTV (הערכה)"
                  value={business.ltv_estimate != null ? formatMoney(business.ltv_estimate) : null}
                />
                <Fact
                  label="פעולות AI"
                  value={business.ai_calls != null ? String(business.ai_calls) : null}
                />
              </dl>
            </Card>

            {/* Subscription control */}
            <SubscriptionPanel
              businessId={business.business_id}
              plans={plans}
              planCode={business.plan_code}
              status={business.status}
              onSaved={handleSaved}
            />

            {/* Sales CRM (M13): stage + next follow-up + notes. */}
            <Card>
              <h2 className="flex items-center gap-2 text-lg font-medium text-slate-900">
                <Icon name="layout-columns" size={20} className="text-leaf" />
                מכירות (CRM)
              </h2>
              <p className="mt-1 text-sm text-slate-500">
                שלב המכירה של העסק בצינור, תזכורת חזרה ויומן פתקים — לניהול הלקוח עד
                שהוא משלם.
              </p>
              <div className="mt-4">
                <CrmPanel
                  businessId={business.business_id}
                  stage={business.crm?.stage ?? 'new'}
                  nextFollowupAt={business.crm?.next_followup_at ?? null}
                  onChanged={handleCrmChanged}
                />
              </div>
            </Card>

            {/* Usage charts */}
            <UsageSection businessId={business.business_id} />

            {/* Danger zone (M13): permanent, irreversible delete. */}
            <Card className="!border-red-200">
              <h2 className="flex items-center gap-2 text-lg font-medium text-red-700">
                <Icon name="trash" size={20} />
                אזור מסוכן
              </h2>
              <p className="mt-1 text-sm text-slate-600">
                מחיקת העסק היא <strong>סופית ובלתי הפיכה</strong> — נמחקים כל
                הנתונים שלו (הבוט, הלידים, הפגישות, השיחות, נתוני השימוש, המנוי
                וה‑CRM). לא ניתן לשחזר.
              </p>
              <button
                type="button"
                onClick={() => {
                  setConfirmText('')
                  setDeleteError(null)
                  setConfirmOpen(true)
                }}
                className="mt-4 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white outline-none transition hover:bg-red-700 focus-visible:ring-2 focus-visible:ring-red-500 focus-visible:ring-offset-2 sm:w-auto"
              >
                <Icon name="trash" size={16} />
                מחיקת העסק
              </button>
            </Card>

            <Modal
              open={confirmOpen}
              title="מחיקת עסק — פעולה בלתי הפיכה"
              onClose={() => {
                if (!deleting) setConfirmOpen(false)
              }}
            >
              <p className="text-sm text-slate-700">
                הפעולה תמחק לצמיתות את{' '}
                <strong>{business.name || 'העסק'}</strong> ואת כל הנתונים שלו. כדי
                לאשר, הקלד/י{' '}
                <span className="font-medium">"{business.name?.trim() || 'מחק'}"</span>:
              </p>
              <input
                type="text"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                placeholder={business.name?.trim() || 'מחק'}
                aria-label="אישור מחיקה"
                className="mt-3 min-h-11 w-full rounded-lg border border-slate-300 px-3 py-2 text-base outline-none focus:border-red-500 focus:ring-2 focus:ring-red-200 sm:text-sm"
              />
              {deleteError ? (
                <div className="mt-3">
                  <Alert tone="error">{deleteError}</Alert>
                </div>
              ) : null}
              {/* בטלפון הכפתורים נערמים ותופסים רוחב מלא (מטרת נגיעה ~44px);
                  מ-sm ומעלה זו שורת אישור/ביטול רגילה מיושרת לסוף. */}
              <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                <button
                  type="button"
                  onClick={() => setConfirmOpen(false)}
                  disabled={deleting}
                  className="min-h-11 rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50"
                >
                  ביטול
                </button>
                <button
                  type="button"
                  onClick={handleDelete}
                  disabled={
                    deleting ||
                    confirmText.trim() !== (business.name?.trim() || 'מחק')
                  }
                  className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {deleting ? 'מוחק…' : 'מחק לצמיתות'}
                </button>
              </div>
            </Modal>
          </>
        ) : null}
      </div>
    </DashboardLayout>
  )
}
