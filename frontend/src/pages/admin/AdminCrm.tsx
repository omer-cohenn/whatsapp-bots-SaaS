// Sales pipeline board (M13, route /admin/crm). A platform-level CRM: every
// business is a card that moves across five stage columns — חדש → יצרתי קשר →
// מחמם → נסגר / אבד — so the operator knows who to work until they pay. Data
// from GET /api/admin/crm.
//
// Moving a card calls PATCH .../crm optimistically (the card jumps columns
// immediately; on failure we roll back and Alert). Opening a card shows a Modal
// with the full CrmPanel (set follow-up, add/read notes). Admin-gated
// server-side; counts + stages only, no end-customer PII.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import DashboardLayout from '../../components/DashboardLayout'
import Spinner from '../../components/ui/Spinner'
import Alert from '../../components/ui/Alert'
import Icon from '../../components/ui/Icon'
import Modal from '../../components/ui/Modal'
import CrmCard from '../../components/admin/CrmCard'
import CrmPanel from '../../components/admin/CrmPanel'
import { getCrm, setCrmStage } from '../../lib/adminClient'
import { toFriendlyError } from '../../lib/friendlyError'
import { CRM_STAGE_META, CRM_STAGE_ORDER } from '../../admin/labels'
import type { CrmBusiness, CrmStage } from '../../admin/types'

export default function AdminCrm() {
  const [businesses, setBusinesses] = useState<CrmBusiness[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // A short-lived banner after a move (success or rollback).
  const [flash, setFlash] = useState<{ tone: 'info' | 'error'; text: string } | null>(
    null,
  )
  // business_id currently mid-move (disables its select).
  const [movingId, setMovingId] = useState<string | null>(null)
  // The business whose detail dialog is open (or null).
  const [openId, setOpenId] = useState<string | null>(null)

  const load = useCallback(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getCrm()
      .then((res) => {
        if (!cancelled) setBusinesses(res.businesses)
      })
      .catch((err) => {
        if (!cancelled) setError(toFriendlyError(err, 'טעינת צינור המכירות נכשלה. נסו שוב.'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => load(), [load])

  // Group cards by stage for the columns.
  const byStage = useMemo(() => {
    const groups: Record<CrmStage, CrmBusiness[]> = {
      new: [],
      contacted: [],
      warming: [],
      won: [],
      lost: [],
    }
    for (const b of businesses) {
      const bucket = groups[b.stage] ?? groups.new
      bucket.push(b)
    }
    return groups
  }, [businesses])

  // Optimistic stage move: update locally, PATCH, roll back on failure.
  async function moveTo(business: CrmBusiness, stage: CrmStage) {
    if (stage === business.stage) return
    const prevStage = business.stage
    setMovingId(business.business_id)
    setFlash(null)
    setBusinesses((list) =>
      list.map((b) => (b.business_id === business.business_id ? { ...b, stage } : b)),
    )
    try {
      const res = await setCrmStage(business.business_id, stage)
      setBusinesses((list) =>
        list.map((b) =>
          b.business_id === business.business_id
            ? { ...b, stage: res.stage, next_followup_at: res.next_followup_at }
            : b,
        ),
      )
      setFlash({
        tone: 'info',
        text: `"${business.name || 'עסק'}" הועבר לשלב "${CRM_STAGE_META[stage].label}".`,
      })
    } catch (err) {
      // Roll back to the previous stage.
      setBusinesses((list) =>
        list.map((b) =>
          b.business_id === business.business_id ? { ...b, stage: prevStage } : b,
        ),
      )
      setFlash({
        tone: 'error',
        text: toFriendlyError(err, 'עדכון השלב נכשל. נסו שוב.'),
      })
    } finally {
      setMovingId(null)
    }
  }

  // Reflect a panel save (stage/follow-up) back into the board card.
  const onPanelChanged = useCallback(
    (id: string, stage: CrmStage, nextFollowupAt: string | null) => {
      setBusinesses((list) =>
        list.map((b) =>
          b.business_id === id ? { ...b, stage, next_followup_at: nextFollowupAt } : b,
        ),
      )
    },
    [],
  )

  const openBusiness = businesses.find((b) => b.business_id === openId) ?? null

  return (
    <DashboardLayout>
      {/* gutter של העמוד עצמו — המעטפת לא מרפדת את <main>. */}
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6 sm:py-10">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900">
            <Icon name="layout-columns" size={22} className="text-leaf" />
            צינור מכירות
          </h1>
          <Link
            to="/admin"
            className="inline-flex min-h-11 items-center gap-1 rounded text-sm font-medium text-leaf-ink sm:min-h-0 underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-leaf focus-visible:ring-offset-2"
          >
            <Icon name="chevron-right" size={16} />
            חזרה לניהול
          </Link>
        </div>

        <p className="text-sm text-slate-600">
          כל עסק הוא כרטיס שנע בין שלבי המכירה. הזיזו כרטיס עם תפריט השלב, או פִּתחו
          אותו כדי לקבוע תזכורת חזרה ולהוסיף פתקים.
          {/* רמז שמופיע רק כשהלוח נגלל אופקית (מתחת ל-lg). */}
          <span className="lg:hidden"> החליקו לצדדים כדי לעבור בין השלבים.</span>
        </p>

        {flash ? <Alert tone={flash.tone}>{flash.text}</Alert> : null}

        {loading ? (
          <Spinner label="טוען צינור מכירות…" className="py-16" />
        ) : error ? (
          <Alert tone="error">{error}</Alert>
        ) : businesses.length === 0 ? (
          <p className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-12 text-center text-sm text-slate-500">
            אין עדיין עסקים בצינור המכירות.
          </p>
        ) : (
          // הלוח נשאר לוח גם בטלפון. מתחת ל-lg אנחנו לא מערימים את חמשת
          // השלבים אחד מתחת לשני — זה הורג את המטאפורה של ה-kanban ומכריח
          // גלילה אנכית אינסופית. במקום זה: רצועה אחת שנגללת אופקית, כל עמודה
          // ברוחב 78vw כך שנראית פיסה מהעמודה הבאה (רמז שאפשר להחליק),
          // עם snap כדי שההחלקה תיעצר בול על עמודה. הגלילה היא של הרצועה
          // בלבד — העמוד עצמו לא נגלל לצדדים.
          //
          // [contain:paint]: ב-RTL, העמודות של הרצועה יושבות בקואורדינטות x
          // שליליות (העמודה החמישית ב--1187px). הדפדפן אמנם לא מאפשר לגלול
          // את העמוד לצדדים — window.scrollX נשאר 0 — אבל הוא כן מדווח על
          // documentElement.scrollWidth מנופח (983 במקום 387), וזו בדיוק
          // הבדיקה המחייבת בחוזה המעטפת. contain:paint אומר לדפדפן שהציור
          // של המכולה חסום בגבולותיה (מה שממילא קורה כאן), וה-scrollWidth
          // חוזר להיות שווה לרוחב החלון. מ-lg זה הופך ל-grid רגיל, אז מבטלים.
          <div className="flex snap-x snap-mandatory gap-3 overflow-x-auto pb-2 [contain:paint] lg:grid lg:grid-cols-5 lg:gap-4 lg:overflow-visible lg:pb-0 lg:[contain:none]">
            {CRM_STAGE_ORDER.map((stage) => {
              const cards = byStage[stage]
              return (
                <section
                  key={stage}
                  aria-label={`שלב: ${CRM_STAGE_META[stage].label}`}
                  className="flex w-[78vw] max-w-[320px] shrink-0 snap-start flex-col gap-3 rounded-2xl bg-[#f4f3ee] p-3 lg:w-auto lg:max-w-none lg:shrink"
                >
                  <div className="flex items-center justify-between gap-2 px-1">
                    <h2 className="flex items-center gap-2 text-sm font-medium text-slate-700">
                      <span
                        aria-hidden="true"
                        className="h-2.5 w-2.5 rounded-full"
                        style={{ backgroundColor: CRM_STAGE_META[stage].color }}
                      />
                      {CRM_STAGE_META[stage].label}
                    </h2>
                    <span className="rounded-full bg-white px-2 py-0.5 text-xs font-medium tabular-nums text-slate-500">
                      {cards.length}
                    </span>
                  </div>

                  <div className="flex flex-col gap-3">
                    {cards.length > 0 ? (
                      cards.map((b) => (
                        <CrmCard
                          key={b.business_id}
                          business={b}
                          busy={movingId === b.business_id}
                          onMove={(s) => void moveTo(b, s)}
                          onOpen={() => setOpenId(b.business_id)}
                        />
                      ))
                    ) : (
                      <p className="px-1 py-3 text-center text-xs text-slate-400">
                        ריק
                      </p>
                    )}
                  </div>
                </section>
              )
            })}
          </div>
        )}
      </div>

      {/* Card detail dialog — full CRM panel for the chosen business. */}
      <Modal
        open={openBusiness !== null}
        title={openBusiness?.name || 'פרטי עסק'}
        onClose={() => setOpenId(null)}
        maxWidthClassName="max-w-lg"
      >
        {openBusiness ? (
          <CrmPanel
            businessId={openBusiness.business_id}
            stage={openBusiness.stage}
            nextFollowupAt={openBusiness.next_followup_at}
            onChanged={(stage, nextFollowupAt) =>
              onPanelChanged(openBusiness.business_id, stage, nextFollowupAt)
            }
          />
        ) : null}
      </Modal>
    </DashboardLayout>
  )
}
