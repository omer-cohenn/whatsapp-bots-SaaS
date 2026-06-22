// Public marketing landing page (shown to visitors who are NOT logged in):
// Omer's "בוטיק" page. This single page is an approved exception to the
// "Tailwind only" rule — it carries its own embedded <style>{CSS}</style> block
// (the bx-* classes) kept 1:1 from the source design. RTL Hebrew throughout.
//
// Real links are wired to the existing routes:
//   - "התחברות" / every "התחילו" / "התחילו חינם" → /auth/google (backend OAuth start)
//   - footer links → /terms, /privacy, /accessibility (react-router)

import { useState, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'

/* ================================================================== */
/*  בוטיק — דף נחיתה: Hero + נתונים + "איך זה עובד" (2x2) + יכולות     */
/*  כרטיסים בגוון שנהב חם (לא לבן), על רקע קרם.                        */
/* ================================================================== */

type ChatMessage = { side: 'user' | 'bot'; text: string; time?: string }

const MESSAGES: ChatMessage[] = [
  { side: 'user', text: 'היי', time: '10:24' },
  { side: 'bot', text: 'ברוכים הבאים לעסק שלך! 👋 אני בוטיק, העוזר החכם שלך. במה אוכל לעזור לך היום?' },
  { side: 'bot', text: 'תן לנו לנהל לך את הוואטסאפ, ואתה תנהל את העסק שלך.' },
  { side: 'bot', text: 'תחסוך שעות יקרות של מענה ללקוחות בוואטסאפ.' },
]
const ESCAPE_TEXT = 'אז למה אתה מחכה?'

type Step = { n: number; key: string; title: string; desc: string }
const STEPS: Step[] = [
  { n: 1, key: 'google', title: 'מתחברים עם Google', desc: 'חשבון ועסק נפתחים אוטומטית — בלי טפסים ארוכים.' },
  { n: 2, key: 'ai', title: 'בונים בוט עם עוזר ה-AI', desc: 'בשפה חופשית, בלי קוד — מתארים, והבוט נבנה.' },
  { n: 3, key: 'whatsapp', title: 'מחברים את הוואטסאפ', desc: 'סריקת QR מהירה — המספר הקיים של העסק.' },
  { n: 4, key: 'config', title: 'מגדירים יכולות', desc: 'לידים, תורים ומענה אנושי — בוחרים מה הבוט יעשה.' },
  { n: 5, key: 'live', title: 'עולים לאוויר', desc: 'הבוט מתחיל לענות ללקוחות 24/7, בלי התערבות.' },
  { n: 6, key: 'leads', title: 'מקבלים לידים ופגישות', desc: 'אוטומטית, ישר לדשבורד שלכם.' },
]

type Feature = { key: string; title: string; desc: string; soon?: boolean }
const FEATURES: Feature[] = [
  { key: 'leads', title: 'איסוף לידים', desc: 'שאלון חכם שאוסף את הפרטים החשובים — שמור ומוצפן.' },
  { key: 'calendar', title: 'קביעת תורים', desc: 'דף הזמנה לעסק, מסונכרן ליומן Google ולפגישות Meet.' },
  { key: 'handoff', title: 'מעבר לנציג אנושי', desc: 'הבוט מזהה צורך ומעביר לצ׳אט חי עם נציג מהצוות.' },
  { key: 'ai', title: 'בונה בוט עם AI', desc: 'מתארים בשפה חופשית — והעוזר בונה את הבוט בשבילכם.' },
  { key: 'dashboard', title: 'דשבורד מלא', desc: 'לידים, שיחות ופגישות — הכול במקום אחד וברור.' },
  { key: 'rag', title: 'מענה מידע מהעסק', desc: 'תשובות מדויקות מתוך הקבצים והאתר של העסק (RAG).', soon: true },
]

type Industry = { key: string; theme: string; title: string; desc: string }
const INDUSTRIES: Industry[] = [
  { key: 'health', theme: 'mint', title: 'קליניקות וטיפול', desc: 'תיאום פגישות ותזכורות ללקוחות.' },
  { key: 'beauty', theme: 'rose', title: 'מספרות וקוסמטיקה', desc: 'קביעת תורים ישירות בוואטסאפ.' },
  { key: 'insurance', theme: 'blue', title: 'סוכני ביטוח', desc: 'איסוף פניות וסינון לידים אוטומטי.' },
  { key: 'service', theme: 'amber', title: 'נותני שירות ובעלי מקצוע', desc: 'הצעות מחיר וזימון קריאות שירות.' },
  { key: 'consult', theme: 'violet', title: 'יועצים ומאמנים', desc: 'מענה ראשוני וקביעת שיחות ייעוץ.' },
]

type Plan = { name: string; amt: string; per: string; popular: boolean; feats: string[] }
const PLANS: Plan[] = [
  { name: 'חינם', amt: 'חינם', per: 'לתמיד', popular: false,
    feats: ['בנייה וניהול של הבוט', 'עד 5 לקוחות', 'מערכת לניהול לידים'] },
  { name: 'מקצועי', amt: '₪150', per: '/לחודש', popular: true,
    feats: ['כל מה שבחינם', 'לקוחות ללא הגבלה', 'קביעת פגישות + סנכרון Google Calendar ו-Meet', 'מענה אנושי מתוך המערכת'] },
  { name: 'עסקי', amt: '₪300', per: '/לחודש', popular: false,
    feats: ['כל מה שבמקצועי', 'מענה חכם ללקוח על סמך העסק שלך (RAG)', 'ריבוי משתמשים'] },
]

type FaqItem = { q: string; a: string }
const FAQ: FaqItem[] = [
  { q: 'צריך לדעת לתכנת?', a: 'לא, בכלל לא. בונים את הבוט בשפה חופשית מול עוזר ה-AI — מתארים מה שצריך והוא מקים את הכול בשבילכם. בלי קוד ובלי הגדרות מסובכות.' },
  { q: 'צריך מספר וואטסאפ חדש?', a: 'לא. הבוט מתחבר למספר הוואטסאפ הקיים של העסק בסריקת QR פשוטה, כך שהלקוחות ממשיכים לכתוב בדיוק לאותו מספר שהם כבר מכירים.' },
  { q: 'הנתונים מאובטחים?', a: 'כן. כל הנתונים מוצפנים ונשמרים לפי תקני אבטחה מקובלים, ורק לכם יש אליהם גישה — דרך הדשבורד האישי שלכם.' },
  { q: 'כמה זמן לוקח להקים?', a: 'כ-10 דקות. מתחברים עם Google, בונים את הבוט בעזרת ה-AI ומחברים את הוואטסאפ — והבוט עולה לאוויר ומתחיל לענות ללקוחות מיד.' },
  { q: 'אפשר לבטל?', a: 'כן, בכל רגע. אין התחייבות וללא קנסות — אפשר לשדרג, להוריד מסלול או לבטל ישירות מהדשבורד, מתי שתרצו.' },
]

/* ----------------------- כלי גילוי בגלילה ------------------------ */
type RevealProps = {
  children: React.ReactNode
  dir?: 'up' | 'left' | 'right'
  delay?: number
  className?: string
}
function Reveal({ children, dir = 'up', delay = 0, className = '' }: RevealProps) {
  const ref = useRef<HTMLDivElement>(null)
  const [vis, setVis] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => { if (e.isIntersecting) { setVis(true); io.unobserve(el) } }),
      { threshold: 0.15 }
    )
    io.observe(el)
    return () => io.disconnect()
  }, [])
  return (
    <div ref={ref} className={`reveal reveal-${dir} ${vis ? 'is-visible' : ''} ${className}`} style={{ transitionDelay: `${delay}ms` }}>
      {children}
    </div>
  )
}

/* ------------------------- מונה מונפש (איטי) --------------------- */
type CounterProps = { from?: number; to: number; duration?: number; suffix?: string }
function Counter({ from = 0, to, duration = 4200, suffix = '' }: CounterProps) {
  const ref = useRef<HTMLSpanElement>(null)
  const [val, setVal] = useState(from)
  const started = useRef(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting && !started.current) {
          started.current = true
          io.unobserve(el)
          const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches
          if (reduce) { setVal(to); return }
          const t0 = performance.now()
          const tick = (now: number) => {
            const t = Math.min((now - t0) / duration, 1)
            const e2 = 1 - Math.pow(1 - t, 3)
            setVal(Math.round(from + (to - from) * e2))
            if (t < 1) requestAnimationFrame(tick)
          }
          requestAnimationFrame(tick)
        }
      })
    }, { threshold: 0.4 })
    io.observe(el)
    return () => io.disconnect()
  }, [from, to, duration])
  return <span ref={ref}>{val}{suffix}</span>
}

/* ----------------------- אייקוני שלבים (לבנים) ------------------- */
function StepIcon({ k }: { k: string }) {
  if (k === 'google')
    return (<svg aria-hidden="true" focusable="false" width="28" height="28" viewBox="0 0 24 24" fill="none"><path d="M12 5a7 7 0 107 7h-6.6" stroke="#fff" strokeWidth="2.3" strokeLinecap="round" /></svg>)
  if (k === 'ai')
    return (<svg aria-hidden="true" focusable="false" width="28" height="28" viewBox="0 0 24 24" fill="none"><path d="M12 3l1.7 4.6L18 9l-4.3 1.6L12 15l-1.7-4.4L6 9l4.3-1.4L12 3z" fill="#fff" /><path d="M18.5 14l.7 1.9 2 .6-2 .7-.7 1.9-.7-1.9-2-.7 2-.6.7-1.9z" fill="#fff" opacity=".9" /></svg>)
  if (k === 'whatsapp')
    return (<svg aria-hidden="true" focusable="false" width="28" height="28" viewBox="0 0 24 24" fill="none"><path d="M6 5h12a2 2 0 012 2v7a2 2 0 01-2 2h-7l-4 3.4V16H6a2 2 0 01-2-2V7a2 2 0 012-2z" fill="#fff" /><circle cx="9" cy="10.5" r="1.1" fill="#46a23f" /><circle cx="12" cy="10.5" r="1.1" fill="#46a23f" /><circle cx="15" cy="10.5" r="1.1" fill="#46a23f" /></svg>)
  if (k === 'config')
    return (<svg aria-hidden="true" focusable="false" width="28" height="28" viewBox="0 0 24 24" fill="none"><path d="M4 7h7M15 7h5M4 12h11M19 12h1M4 17h3M11 17h9" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" /><circle cx="13" cy="7" r="2.1" fill="#3f9a39" stroke="#fff" strokeWidth="1.8" /><circle cx="17" cy="12" r="2.1" fill="#3f9a39" stroke="#fff" strokeWidth="1.8" /><circle cx="9" cy="17" r="2.1" fill="#3f9a39" stroke="#fff" strokeWidth="1.8" /></svg>)
  if (k === 'live')
    return (<svg aria-hidden="true" focusable="false" width="28" height="28" viewBox="0 0 24 24" fill="none"><path d="M12 2.5c2.8 1.6 4.2 4.4 4.2 7.8 0 1.5-.5 2.9-1.3 3.9H9.1c-.8-1-1.3-2.4-1.3-3.9C7.8 6.9 9.2 4.1 12 2.5z" fill="#fff" /><circle cx="12" cy="8.4" r="1.5" fill="#3f9a39" /><path d="M9.2 15l-1.7 4 3-1.4M14.8 15l1.7 4-3-1.4" stroke="#fff" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" fill="none" /></svg>)
  return (<svg aria-hidden="true" focusable="false" width="28" height="28" viewBox="0 0 24 24" fill="none"><circle cx="9" cy="8.5" r="2.6" fill="#fff" /><circle cx="16" cy="9.5" r="2" fill="#fff" opacity=".9" /><path d="M4.5 18c0-2.5 2-4.3 4.5-4.3s4.5 1.8 4.5 4.3" stroke="#fff" strokeWidth="2" strokeLinecap="round" fill="none" /><path d="M14.5 17.6c.2-2 1.7-3.4 3.7-3.4 1.6 0 2.9.9 3.4 2.3" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" fill="none" opacity=".9" /></svg>)
}

/* ---------------------- אייקוני יכולות (קו) --------------------- */
function FeatIcon({ k }: { k: string }) {
  const p = { width: 24, height: 24, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }
  if (k === 'leads')
    return (<svg aria-hidden="true" focusable="false" {...p}><circle cx="9" cy="8" r="3" /><path d="M3.5 19a5.5 5.5 0 0111 0" /><path d="M16 6.2a3 3 0 010 5.6" /><path d="M18.5 19a5.5 5.5 0 00-3-4.9" /></svg>)
  if (k === 'calendar')
    return (<svg aria-hidden="true" focusable="false" {...p}><rect x="4" y="5" width="16" height="15" rx="2" /><path d="M4 9.5h16M8 3v3.5M16 3v3.5" /><rect x="7.5" y="12.5" width="3" height="3" rx=".6" fill="currentColor" stroke="none" /></svg>)
  if (k === 'handoff')
    return (<svg aria-hidden="true" focusable="false" {...p}><path d="M5 5h14a2 2 0 012 2v6.5a2 2 0 01-2 2h-8L7 19v-3.5H5a2 2 0 01-2-2V7a2 2 0 012-2z" /><path d="M8.5 10.2h.01M12 10.2h.01M15.5 10.2h.01" /></svg>)
  if (k === 'ai')
    return (<svg aria-hidden="true" focusable="false" {...p}><path d="M12 3l1.7 4.6L18 9l-4.3 1.6L12 15l-1.7-4.4L6 9l4.3-1.4L12 3z" fill="currentColor" stroke="none" /><path d="M18.4 14.2l.6 1.7 1.8.6-1.8.6-.6 1.7-.6-1.7-1.8-.6 1.8-.6.6-1.7z" fill="currentColor" stroke="none" /></svg>)
  if (k === 'dashboard')
    return (<svg aria-hidden="true" focusable="false" {...p}><rect x="5" y="8" width="14" height="10" rx="3" /><path d="M12 8V5.5" /><circle cx="12" cy="4" r="1.3" fill="currentColor" stroke="none" /><circle cx="9.6" cy="13" r="1.1" fill="currentColor" stroke="none" /><circle cx="14.4" cy="13" r="1.1" fill="currentColor" stroke="none" /><path d="M3.2 12v2.5M20.8 12v2.5" /></svg>)
  return (<svg aria-hidden="true" focusable="false" {...p}><circle cx="12" cy="12" r="8.5" /><path d="M3.6 12h16.8M12 3.5c2.4 2.3 2.4 14.7 0 17M12 3.5c-2.4 2.3-2.4 14.7 0 17" /></svg>)
}

/* ============================== HERO ============================== */
function HeroSection() {
  const [count, setCount] = useState(0)
  const [typing, setTyping] = useState(false)
  const [vibrate, setVibrate] = useState(false)
  const [escape, setEscape] = useState(false)
  const [isMobile, setIsMobile] = useState(false)
  const bodyRef = useRef<HTMLDivElement>(null)
  const timers = useRef<ReturnType<typeof setTimeout>[]>([])

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < 900)
    onResize()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTo({ top: bodyRef.current.scrollHeight, behavior: 'smooth' })
  }, [count, typing])

  useEffect(() => {
    const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduce) { setCount(MESSAGES.length); setEscape(true); return }
    const after = (ms: number, fn: () => void) => timers.current.push(setTimeout(fn, ms))
    const run = () => {
      setCount(0); setTyping(false); setVibrate(false); setEscape(false)
      after(800, () => { setCount(1); setVibrate(true) })
      after(1300, () => setVibrate(false))
      after(2000, () => setTyping(true))
      after(4000, () => { setTyping(false); setCount(2) })
      after(6850, () => setCount(3))
      after(9700, () => setCount(4))
      after(12550, () => setEscape(true))
      after(18400, run)
    }
    run()
    return () => { timers.current.forEach(clearTimeout); timers.current = [] }
  }, [])

  const tilt = isMobile
    ? 'perspective(1500px) rotateY(-7deg) rotateZ(-1deg) scale(.86)'
    : 'perspective(1600px) rotateY(-14deg) rotateX(3deg) rotateZ(-1.5deg)'

  return (
    <section className="bx-hero">
      <div className="bx-blob" />
      <header className="bx-brand">
        <div className="bx-logo">
          <span className="bx-logo-mark">
            <svg aria-hidden="true" focusable="false" width="20" height="20" viewBox="0 0 24 24" fill="none">
              <path d="M12 2a10 10 0 00-8.7 14.9L2 22l5.3-1.4A10 10 0 1012 2z" fill="#fff" />
              <circle cx="9" cy="12" r="1.6" fill="#0a7d40" /><circle cx="15" cy="12" r="1.6" fill="#0a7d40" />
            </svg>
          </span>
          <div className="bx-logo-text"><strong>בוטיק</strong><small>העוזר החכם לוואטסאפ</small></div>
        </div>
        <a className="bx-nav-cta" href="/auth/google">התחברות</a>
      </header>

      <div className="bx-main">
        <div className="bx-col-text">
          <span className="bx-eyebrow">העוזר החכם לעסק שלך</span>
          <h1 className="bx-headline">
            הבוט שעונה ללקוחות, אוסף לידים וקובע פגישות
            <span className="bx-accent"> — אוטומטית בוואטסאפ.</span>
          </h1>
          <p className="bx-lead-text">
            בלי קוד, בלי מפתח, בלי אפליקציה ללקוח. מקימים בוט חכם בדקות, מחברים את הוואטסאפ של העסק —
            והוא עובד בשבילכם 24/7.
          </p>
        </div>

        <div className="bx-col-phone">
          <div className="bx-phone-wrap">
            <div className="bx-tilt" style={{ transform: tilt }}>
              <div className={`bx-phone ${vibrate ? 'bx-vibrate' : ''}`}>
                <div className="bx-notch" />
                <div className="bx-screen">
                  <div className="bx-wa-header">
                    <svg aria-hidden="true" focusable="false" className="bx-wa-back" width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M9 6l6 6-6 6" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></svg>
                    <div className="bx-wa-ava"><svg aria-hidden="true" focusable="false" width="20" height="20" viewBox="0 0 24 24"><circle cx="8" cy="11" r="1.7" fill="#fff" /><circle cx="16" cy="11" r="1.7" fill="#fff" /><rect x="9" y="15" width="6" height="2" rx="1" fill="#cdeee2" /></svg></div>
                    <div className="bx-wa-id"><strong>בוטיק · העוזר החכם</strong><span>{typing ? 'מקליד…' : 'מחובר'}</span></div>
                  </div>
                  <div className="bx-wa-body" ref={bodyRef}>
                    {MESSAGES.slice(0, count).map((m, i) => (
                      <div key={i} className={`bx-msg ${m.side === 'user' ? 'bx-user' : 'bx-bot'} bx-msg-anim`}>
                        <p>{m.text}</p>
                        <span className={`bx-time ${m.side === 'user' ? 'bx-time-user' : ''}`}>{m.side === 'user' ? '10:24 ✓✓' : '10:24'}</span>
                      </div>
                    ))}
                    {typing && (<div className="bx-msg bx-bot bx-typing"><span style={{ animationDelay: '0s' }} /><span style={{ animationDelay: '.2s' }} /><span style={{ animationDelay: '.4s' }} /></div>)}
                  </div>
                  <div className="bx-wa-input"><div className="bx-input-pill">הקלד הודעה…</div><div className="bx-send"><svg aria-hidden="true" focusable="false" width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M4 12l16-8-6 8 6 8-16-8z" fill="#fff" /></svg></div></div>
                </div>
              </div>
            </div>
            {escape && (
              <div className="bx-escape bx-escape-anim">
                <div className="bx-escape-bob">
                  <div className="bx-escape-bubble"><p>{ESCAPE_TEXT}</p></div>
                  <div className="bx-escape-arrow"><svg aria-hidden="true" focusable="false" width="20" height="20" viewBox="0 0 24 24" fill="none"><path d="M12 4v15M5 13l7 7 7-7" stroke="#3a9d4f" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" /></svg></div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="bx-scroll">
        <span>גללו לגילוי כל היכולות</span>
        <svg aria-hidden="true" focusable="false" width="24" height="24" viewBox="0 0 24 24" fill="none" className="bx-chev"><path d="M6 9l6 6 6-6" stroke="#3a9d4f" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </div>
    </section>
  )
}

/* ===================== נתונים בתיבות (שנהב) ===================== */
function StatsBand() {
  const stats = [
    { dir: 'right' as const, d: 0, num: (<><Counter to={10} /><span className="bx-stat-unit">דק'</span></>), label: 'להקמה מלאה' },
    { dir: 'right' as const, d: 90, num: (<><Counter to={98} /><span className="bx-stat-unit">%</span></>), label: 'פתיחה להודעות בוואטסאפ' },
    { dir: 'left' as const, d: 90, num: (<Counter from={50} to={0} />), label: 'הודעות שמתפספסות' },
    { dir: 'left' as const, d: 0, num: (<span className="bx-stat-static">24/7</span>), label: 'זמינות מלאה' },
  ]
  return (
    <section className="bx-stats">
      <div className="bx-grid4">
        {stats.map((s, i) => (
          <Reveal key={i} dir={s.dir} delay={s.d}>
            <div className="bx-stat">
              <div className="bx-stat-box"><div className="bx-stat-num">{s.num}</div></div>
              <div className="bx-stat-label">{s.label}</div>
            </div>
          </Reveal>
        ))}
      </div>
    </section>
  )
}

/* ============ איך זה עובד — קונטיינרים ברשת 2x2 מרווחת ========== */
function HowItWorks() {
  const [active, setActive] = useState(0)
  useEffect(() => {
    const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduce) { setActive(STEPS.length - 1); return }
    const id = setInterval(() => setActive((a) => (a + 1) % STEPS.length), 4500)
    return () => clearInterval(id)
  }, [])

  return (
    <section className="bx-hiw">
      <Reveal dir="up" className="bx-hiw-head">
        <h2 className="bx-hiw-title">איך זה עובד</h2>
        <p className="bx-hiw-sub">מסלול קצר מההרשמה ועד הלידים הראשונים.</p>
      </Reveal>

      <div className="bx-hiw-grid">
        {STEPS.map((s, i) => {
          const col = i % 3
          const dir = col === 0 ? 'right' : col === 2 ? 'left' : 'up'
          return (
            <Reveal key={s.n} dir={dir} delay={col * 80}>
              <div className={`bx-card-tile bx-hcard ${active === i ? 'active' : ''}`} onMouseEnter={() => setActive(i)}>
                <div className="bx-node-circle"><StepIcon k={s.key} /><span className="bx-node-badge">{s.n}</span></div>
                <h3 className="bx-hcard-title">{s.title}</h3>
                <p className="bx-hcard-desc">{s.desc}</p>
              </div>
            </Reveal>
          )
        })}
      </div>
    </section>
  )
}

/* ===================== יכולות — "כל מה שהעסק צריך" ============== */
function FeaturesSection() {
  return (
    <section className="bx-feats">
      <Reveal dir="up" className="bx-feats-head">
        <h2 className="bx-feats-title">כל מה שהעסק צריך — <span className="bx-accent">בבוט אחד</span></h2>
        <p className="bx-feats-sub">יכולות שעובדות בשבילכם, בלי להרים אצבע.</p>
      </Reveal>

      <div className="bx-feats-grid">
        {FEATURES.map((f, i) => {
          const col = i % 3
          const dir = col === 0 ? 'right' : col === 2 ? 'left' : 'up'
          return (
            <Reveal key={f.key} dir={dir} delay={col * 80}>
              <div className="bx-card-tile bx-feat">
                {f.soon && <span className="bx-feat-soon">בקרוב</span>}
                <div className="bx-feat-icon"><FeatIcon k={f.key} /></div>
                <h3 className="bx-feat-title">{f.title}</h3>
                <p className="bx-feat-desc">{f.desc}</p>
              </div>
            </Reveal>
          )
        })}
      </div>
    </section>
  )
}

/* ============ תמונות מונפשות לכל תחום (איורים צבעוניים) ========= */
function UseCaseArt({ k }: { k: string }) {
  const org = { transformBox: 'fill-box' as const, transformOrigin: 'center' }
  if (k === 'health')
    return (
      <svg aria-hidden="true" focusable="false" viewBox="0 0 140 92" fill="none">
        <circle cx="22" cy="24" r="6" fill="#fff" opacity=".55" className="bx-flo" style={org} />
        <circle cx="118" cy="64" r="7" fill="currentColor" opacity=".22" className="bx-flo2" style={org} />
        <g className="bx-beat" style={org}><path d="M70 70c-17-10-27-20-27-33a14 14 0 0127-7 14 14 0 0127 7c0 13-10 23-27 33z" fill="currentColor" /></g>
        <path d="M26 50h20l5-12 7 24 6-14 4 8h42" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" className="bx-draw" />
        <g className="bx-flo2" style={org}><rect x="98" y="15" width="18" height="18" rx="5" fill="#fff" /><path d="M107 20v8M103 24h8" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" /></g>
      </svg>
    )
  if (k === 'beauty')
    return (
      <svg aria-hidden="true" focusable="false" viewBox="0 0 140 92" fill="none">
        <g className="bx-twk" style={org}><path d="M26 18l2.4 6.6 6.6 2.4-6.6 2.4-2.4 6.6-2.4-6.6-6.6-2.4 6.6-2.4z" fill="#fff" /></g>
        <g className="bx-twk2" style={org}><path d="M114 58l2 5.6 5.6 2-5.6 2-2 5.6-2-5.6-5.6-2 5.6-2z" fill="currentColor" /></g>
        <g className="bx-sway" style={{ transformBox: 'fill-box', transformOrigin: '70px 72px' }}>
          <circle cx="54" cy="72" r="8" stroke="currentColor" strokeWidth="3.4" fill="none" />
          <circle cx="72" cy="72" r="8" stroke="currentColor" strokeWidth="3.4" fill="none" />
          <path d="M58 67l40-40M68 67L30 30" stroke="currentColor" strokeWidth="3.4" strokeLinecap="round" />
          <circle cx="63" cy="52" r="3" fill="currentColor" />
        </g>
      </svg>
    )
  if (k === 'insurance')
    return (
      <svg aria-hidden="true" focusable="false" viewBox="0 0 140 92" fill="none">
        <circle cx="20" cy="22" r="6" fill="currentColor" opacity=".2" className="bx-flo" style={org} />
        <circle cx="120" cy="66" r="5" fill="#fff" opacity=".6" className="bx-flo2" style={org} />
        <g className="bx-flo" style={org}>
          <path d="M70 14l30 10v18c0 18-13 30-30 36-17-6-30-18-30-36V24z" fill="currentColor" />
          <path d="M58 46l9 9 19-19" stroke="#fff" strokeWidth="4.4" strokeLinecap="round" strokeLinejoin="round" />
        </g>
      </svg>
    )
  if (k === 'service')
    return (
      <svg aria-hidden="true" focusable="false" viewBox="0 0 140 92" fill="none">
        <circle cx="24" cy="24" r="6" fill="#fff" opacity=".55" className="bx-flo" style={org} />
        <circle cx="116" cy="68" r="6" fill="currentColor" opacity=".2" className="bx-flo2" style={org} />
        <circle cx="70" cy="46" r="17" stroke="currentColor" strokeWidth="9" fill="none" strokeDasharray="6 7.6" className="bx-spin" style={org} />
        <circle cx="70" cy="46" r="8" fill="#fff" stroke="currentColor" strokeWidth="4" />
      </svg>
    )
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 140 92" fill="none">
      <circle cx="70" cy="40" r="23" fill="currentColor" opacity=".16" className="bx-glow" style={org} />
      <g className="bx-twk" style={org}><path d="M70 8v6M49 18l4 4M91 18l-4 4M40 40h6M94 40h6" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" /></g>
      <g className="bx-flo" style={org}>
        <path d="M70 22a16 16 0 00-9 29c2 1.5 3 3 3 5v2h12v-2c0-2 1-3.5 3-5a16 16 0 00-9-29z" fill="currentColor" />
        <rect x="64" y="60" width="12" height="5" rx="2" fill="currentColor" />
        <rect x="66" y="67" width="8" height="4" rx="2" fill="currentColor" />
      </g>
      <g className="bx-twk2" style={org}><rect x="20" y="72" width="6" height="10" rx="2" fill="#fff" /><rect x="29" y="66" width="6" height="16" rx="2" fill="#fff" /><rect x="38" y="60" width="6" height="22" rx="2" fill="#fff" /></g>
    </svg>
  )
}

/* ============= מתאים לכל עסק שמדבר עם לקוחות (תחומים) =========== */
function IndustriesSection() {
  return (
    <section className="bx-ind">
      <Reveal dir="up" className="bx-ind-head">
        <h2 className="bx-ind-title">מתאים לכל עסק שמדבר עם לקוחות</h2>
        <p className="bx-ind-sub">יהיה התחום אשר יהיה — הבוט מדבר את השפה של הלקוחות שלכם.</p>
      </Reveal>

      <div className="bx-ind-grid">
        {INDUSTRIES.map((it, i) => {
          const m = i % 3
          const dir = m === 0 ? 'right' : m === 2 ? 'left' : 'up'
          return (
            <Reveal key={it.key} dir={dir} delay={m * 80}>
              <div className={`bx-card-tile bx-uc bx-th-${it.theme}`}>
                <div className={`bx-uc-img bx-uc-${it.theme}`}>
                  <span className="bx-uc-shine" />
                  <UseCaseArt k={it.key} />
                </div>
                <div className="bx-uc-body">
                  <h3 className="bx-uc-title">{it.title}</h3>
                  <p className="bx-uc-desc">{it.desc}</p>
                </div>
              </div>
            </Reveal>
          )
        })}
      </div>
    </section>
  )
}

/* =================== מסלולים (Pricing) ========================== */
function PricingSection() {
  return (
    <section className="bx-pricing">
      <Reveal dir="up" className="bx-pricing-head">
        <h2 className="bx-pricing-title">מסלולים פשוטים, בלי הפתעות</h2>
        <p className="bx-pricing-sub">מתחילים בחינם, משדרגים כשהעסק צומח.</p>
      </Reveal>

      <div className="bx-pricing-grid">
        {PLANS.map((pl, i) => {
          const dir = i === 0 ? 'right' : i === 2 ? 'left' : 'up'
          return (
            <Reveal key={pl.name} dir={dir} delay={i * 80}>
              <div className={`bx-card-tile bx-plan ${pl.popular ? 'bx-plan-pop' : ''}`}>
                <div className="bx-plan-top">
                  <h3 className="bx-plan-name">{pl.name}</h3>
                  {pl.popular && <span className="bx-plan-badge">הכי פופולרי</span>}
                </div>
                <div className="bx-plan-price">
                  <span className="bx-plan-amt">{pl.amt}</span>
                  <span className="bx-plan-per">{pl.per}</span>
                </div>
                <ul className="bx-plan-feats">
                  {pl.feats.map((f, j) => (
                    <li key={j}>
                      <svg aria-hidden="true" focusable="false" width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M5 12.5l4.5 4.5L19 7" stroke="#3f9a39" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>
                <a className={`bx-plan-cta ${pl.popular ? 'pop' : ''}`} href="/auth/google">התחילו</a>
              </div>
            </Reveal>
          )
        })}
      </div>
    </section>
  )
}

/* =================== שאלות נפוצות (FAQ) ========================= */
function FaqSection() {
  const [open, setOpen] = useState(0)
  return (
    <section className="bx-faq">
      <Reveal dir="up" className="bx-faq-head">
        <h2 className="bx-faq-title">שאלות נפוצות</h2>
      </Reveal>
      <div className="bx-faq-list">
        {FAQ.map((item, i) => (
          <Reveal key={i} dir="up" delay={i * 60}>
            <div className={`bx-card-tile bx-faq-item ${open === i ? 'open' : ''}`}>
              <button className="bx-faq-q" type="button" onClick={() => setOpen(open === i ? -1 : i)} aria-expanded={open === i}>
                <span>{item.q}</span>
                <svg aria-hidden="true" focusable="false" className="bx-faq-chev" width="20" height="20" viewBox="0 0 24 24" fill="none"><path d="M6 9l6 6 6-6" stroke="#3f9a39" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
              </button>
              <div className="bx-faq-a-wrap"><div className="bx-faq-a"><p>{item.a}</p></div></div>
            </div>
          </Reveal>
        ))}
      </div>
    </section>
  )
}

/* =================== CTA סופי + פוטר ============================ */
function Footer() {
  return (
    <>
      <section className="bx-cta-band">
        <span className="bx-cta-deco bx-flo" style={{ width: 120, height: 120, top: '-30px', insetInlineStart: '8%' }} />
        <span className="bx-cta-deco bx-flo2" style={{ width: 70, height: 70, bottom: '12%', insetInlineStart: '20%' }} />
        <span className="bx-cta-deco bx-flo" style={{ width: 160, height: 160, top: '10%', insetInlineEnd: '6%' }} />
        <span className="bx-cta-deco bx-flo2" style={{ width: 54, height: 54, bottom: '18%', insetInlineEnd: '24%' }} />
        <Reveal dir="up" className="bx-cta-inner">
          <h2>מוכנים להתחיל?</h2>
          <p>חיבור מהיר, בלי קוד — והבוט עובד בשבילכם כבר היום.</p>
          <a className="bx-cta-white" href="/auth/google">
            <svg aria-hidden="true" focusable="false" width="20" height="20" viewBox="0 0 24 24" fill="none"><path d="M12 2a10 10 0 00-8.7 14.9L2 22l5.3-1.4A10 10 0 1012 2z" fill="#2f7a2a" /><path d="M8.4 7.6c.2-.5.4-.5.7-.5h.6c.2 0 .4 0 .6.5l.7 1.6c.1.2 0 .4-.1.6l-.4.5c-.2.2-.2.3-.1.5.3.6 1 1.5 1.9 2 .3.2.5.2.7 0l.5-.5c.2-.2.3-.2.5-.1l1.6.7c.2.1.4.3.4.5 0 .7-.3 1.4-1 1.6-.6.2-1.4.2-3.1-.7-1.9-1-3.1-2.9-3.2-3-.1-.1-.8-1-.8-2 0-.9.5-1.4.7-1.6z" fill="#fff" /></svg>
            התחילו חינם
          </a>
        </Reveal>
      </section>

      <footer className="bx-footer">
        <div className="bx-footer-inner">
          <div className="bx-footer-brand">
            <span className="bx-logo-mark">
              <svg aria-hidden="true" focusable="false" width="20" height="20" viewBox="0 0 24 24" fill="none"><path d="M12 2a10 10 0 00-8.7 14.9L2 22l5.3-1.4A10 10 0 1012 2z" fill="#fff" /><circle cx="9" cy="12" r="1.6" fill="#0a7d40" /><circle cx="15" cy="12" r="1.6" fill="#0a7d40" /></svg>
            </span>
            <div className="bx-footer-name"><strong>בוטיק</strong><small>העוזר החכם לוואטסאפ</small></div>
          </div>
          <nav className="bx-footer-links">
            <Link to="/terms">תנאי שימוש</Link>
            <Link to="/privacy">מדיניות פרטיות</Link>
            <Link to="/accessibility">הצהרת נגישות</Link>
          </nav>
        </div>
        <div className="bx-footer-bottom">© 2026 בוטיק · כל הזכויות שמורות</div>
      </footer>
    </>
  )
}

/* ============================ הדף השלם =========================== */
export default function LandingPage() {
  return (
    <div dir="rtl" className="bx-page">
      <style>{CSS}</style>
      <HeroSection />
      <StatsBand />
      <HowItWorks />
      <FeaturesSection />
      <IndustriesSection />
      <PricingSection />
      <FaqSection />
      <Footer />
    </div>
  )
}

const CSS = `
@import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@500;600;700&family=Heebo:wght@400;500;600;700;800&family=Rubik:wght@500;600;700;800&display=swap');

.bx-page{position:relative;font-family:'Heebo',system-ui,sans-serif;background:#f6f3eb;color:#1b3a28;overflow-x:hidden;}

/* גילוי בגלילה — החלקה עדינה מהצדדים */
.reveal{opacity:0;transition:opacity .85s cubic-bezier(.16,.8,.3,1),transform .85s cubic-bezier(.16,.8,.3,1);will-change:opacity,transform;}
.reveal-right{transform:translateX(54px);}
.reveal-left{transform:translateX(-54px);}
.reveal-up{transform:translateY(36px);}
.reveal.is-visible{opacity:1;transform:none;}

/* כרטיס בסיס — גוון שנהב חם (לא לבן) */
.bx-card-tile{background:linear-gradient(160deg,#fcf9f2,#f4efe2);border:1px solid #e8e0cf;border-radius:22px;
  box-shadow:0 12px 30px rgba(70,60,35,.07);
  transition:transform .45s cubic-bezier(.16,.8,.3,1),box-shadow .45s,border-color .45s;}

/* ---------- HERO ---------- */
.bx-hero{position:relative;min-height:100vh;display:flex;flex-direction:column;overflow:hidden;isolation:isolate;}
.bx-blob{position:absolute;top:-10%;left:-6%;width:55%;height:80%;z-index:-1;pointer-events:none;background:radial-gradient(closest-side,rgba(79,160,70,.16),transparent 75%);filter:blur(8px);}
.bx-brand{display:flex;align-items:center;justify-content:space-between;padding:22px 40px;}
.bx-logo{display:flex;align-items:center;gap:11px;}
.bx-logo-mark{display:grid;place-items:center;width:40px;height:40px;border-radius:13px;background:linear-gradient(145deg,#5cb04e,#3f9a39);box-shadow:0 6px 16px rgba(63,154,57,.28);}
.bx-logo-text{display:flex;flex-direction:column;line-height:1.05;}
.bx-logo-text strong{font-family:'Rubik';font-weight:800;font-size:19px;color:#1b3a28;}
.bx-logo-text small{font-size:11.5px;color:#7c8a7f;}
.bx-nav-cta{font-size:14px;font-weight:700;color:#2c5a3c;text-decoration:none;padding:9px 18px;border:1.5px solid #d3cdbd;border-radius:999px;background:transparent;transition:.2s;}
.bx-nav-cta:hover{border-color:#bcd9b8;color:#2f7a44;background:rgba(63,154,57,.06);}
.bx-main{flex:1;display:flex;align-items:center;justify-content:center;gap:54px;width:100%;max-width:1180px;margin:0 auto;padding:8px 40px 20px;}
.bx-col-text{flex:1;max-width:560px;}
.bx-eyebrow{display:inline-block;font-size:13px;font-weight:700;color:#3f9a39;letter-spacing:.4px;background:#e7f4e1;padding:6px 13px;border-radius:999px;margin-bottom:18px;}
.bx-headline{margin:0;font-family:'Rubik';font-weight:800;letter-spacing:-.4px;line-height:1.18;font-size:clamp(30px,3.9vw,46px);color:#1b3a28;}
.bx-accent{color:#4aa343;}
.bx-lead-text{margin:20px 0 0;font-size:17px;line-height:1.75;color:#6b776c;max-width:500px;}
.bx-col-phone{flex:none;display:flex;flex-direction:column;align-items:center;}
.bx-phone-wrap{position:relative;}
.bx-tilt{transform-style:preserve-3d;will-change:transform;}
.bx-phone{position:relative;width:252px;height:518px;background:#0e120f;border-radius:42px;padding:9px;box-shadow:-26px 30px 60px rgba(34,52,38,.28),0 0 0 2px #20271f;}
.bx-notch{position:absolute;top:18px;left:50%;transform:translateX(-50%);width:88px;height:23px;background:#000;border-radius:13px;z-index:5;}
.bx-screen{position:relative;width:100%;height:100%;border-radius:33px;overflow:hidden;background:#e6ddd2;display:flex;flex-direction:column;}
.bx-vibrate{animation:bxVibrate .5s ease-in-out 1;}
@keyframes bxVibrate{0%,100%{transform:translateX(0)}33%{transform:translateX(-.4px)}66%{transform:translateX(.4px)}}
.bx-wa-header{display:flex;align-items:center;gap:9px;padding:38px 13px 11px;background:#0a8a5f;flex:none;}
.bx-wa-back{flex:none;opacity:.95;}
.bx-wa-ava{width:33px;height:33px;border-radius:50%;background:#2f9e8c;display:grid;place-items:center;flex:none;}
.bx-wa-id{display:flex;flex-direction:column;line-height:1.25;}
.bx-wa-id strong{font-size:13px;color:#fff;font-weight:700;}
.bx-wa-id span{font-size:11px;color:#cdeee2;}
.bx-wa-body{flex:1;min-height:0;overflow-y:auto;padding:14px 12px;display:flex;flex-direction:column;gap:9px;background-color:#e6ddd2;background-image:radial-gradient(rgba(0,0,0,.03) 1px,transparent 1px);background-size:18px 18px;scrollbar-width:none;}
.bx-wa-body::-webkit-scrollbar{display:none;}
.bx-msg{max-width:80%;padding:7px 10px 5px;border-radius:12px;font-size:13.5px;line-height:1.5;position:relative;box-shadow:0 1px 1px rgba(0,0,0,.1);flex:none;}
.bx-msg p{margin:0;color:#0e2118;}
.bx-time{display:block;font-size:9.5px;color:#5b6b64;text-align:start;margin-top:2px;}
.bx-time-user{color:#4f9165;}
.bx-user{align-self:flex-end;background:#d7f3c4;border-top-right-radius:3px;}
.bx-bot{align-self:flex-start;background:#fff;border-top-left-radius:3px;}
.bx-msg-anim{animation:bxMsgIn 2.1s cubic-bezier(.16,.8,.3,1) both;}
@keyframes bxMsgIn{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}
.bx-typing{display:flex;gap:4px;align-items:center;padding:11px 12px;}
.bx-typing span{width:7px;height:7px;border-radius:50%;background:#9aa79e;animation:bxType 1.3s infinite;}
@keyframes bxType{0%,60%,100%{transform:translateY(0);opacity:.4}30%{transform:translateY(-3px);opacity:1}}
.bx-wa-input{flex:none;display:flex;align-items:center;gap:7px;padding:8px 10px;background:#e6ddd2;}
.bx-input-pill{flex:1;background:#fff;border-radius:999px;padding:8px 13px;font-size:12px;color:#9aa6a0;}
.bx-send{width:34px;height:34px;border-radius:50%;background:#0a8a5f;display:grid;place-items:center;flex:none;}
.bx-escape{position:absolute;bottom:-28px;left:50%;transform:translateX(-50%);z-index:40;width:max-content;}
.bx-escape-anim{animation:bxEscape 2s cubic-bezier(.16,.8,.3,1) both;}
@keyframes bxEscape{from{opacity:0;transform:translate(-50%,-10px)}to{opacity:1;transform:translate(-50%,0)}}
.bx-escape-bob{animation:bxEscBob 4.5s ease-in-out infinite;}
@keyframes bxEscBob{0%,100%{transform:translateY(0)}50%{transform:translateY(-3px)}}
.bx-escape-bubble{position:relative;background:linear-gradient(150deg,#eafcef,#cdf3da);border-radius:16px;padding:11px 18px;box-shadow:0 16px 34px rgba(63,154,57,.26),0 0 0 1px rgba(63,154,57,.4);}
.bx-escape-bubble p{margin:0;font-family:'Fredoka','Rubik',sans-serif;font-weight:700;font-size:18px;color:#2f8a45;text-align:center;white-space:nowrap;letter-spacing:.2px;}
.bx-escape-bubble::after{content:"";position:absolute;top:-5px;inset-inline-start:50%;margin-inline-start:-6px;width:12px;height:12px;background:#eafcef;transform:rotate(45deg);}
.bx-escape-arrow{display:grid;place-items:center;margin-top:5px;animation:bxArrow 2s ease-in-out infinite;}
@keyframes bxArrow{0%,100%{transform:translateY(0);opacity:.7}50%{transform:translateY(5px);opacity:1}}
.bx-scroll{display:flex;flex-direction:column;align-items:center;gap:2px;padding:6px 0 26px;}
.bx-scroll span{font-size:12.5px;color:#8a958b;}
.bx-chev{animation:bxChev 2.2s ease-in-out infinite;}
@keyframes bxChev{0%,100%{transform:translateY(0);opacity:.5}50%{transform:translateY(6px);opacity:1}}

/* ---------- נתונים ---------- */
.bx-stats{padding:62px 40px 22px;}
.bx-grid4{max-width:1120px;margin:0 auto;display:grid;grid-template-columns:repeat(4,1fr);gap:22px;}
.bx-grid4 > .reveal{display:flex;}
.bx-stat{flex:1;display:flex;flex-direction:column;align-items:center;text-align:center;}
.bx-stat-box{width:100%;display:flex;align-items:center;justify-content:center;padding:18px 12px;}
.bx-stat-num{font-family:'Rubik';font-weight:600;font-size:clamp(38px,4.6vw,56px);color:#878c86;line-height:1;display:inline-flex;align-items:baseline;gap:5px;direction:ltr;}
.bx-stat-unit{font-size:.46em;font-weight:600;color:#a4a99f;}
.bx-stat-static{display:inline-block;}
.bx-stat-label{margin-top:15px;font-size:14.5px;color:#5e6b62;font-weight:600;}

/* ---------- איך זה עובד — רשת 2x2 ---------- */
.bx-hiw{padding:48px 40px 70px;}
.bx-hiw-head{text-align:center;max-width:640px;margin:0 auto 46px;}
.bx-hiw-title{margin:0;font-family:'Rubik';font-weight:800;font-size:clamp(28px,3.6vw,40px);color:#1b3a28;}
.bx-hiw-sub{margin:12px 0 0;font-size:16.5px;color:#6b776c;}
.bx-hiw-grid{max-width:1120px;margin:0 auto;display:grid;grid-template-columns:repeat(3,1fr);gap:26px;}
.bx-hiw-grid > .reveal{display:flex;}
.bx-hcard{flex:1;display:flex;flex-direction:column;align-items:flex-start;text-align:right;padding:28px 28px;}
.bx-hcard:hover{transform:translateY(-4px);box-shadow:0 20px 40px rgba(70,60,35,.13);border-color:#dcebd2;}
.bx-hcard.active{border-color:#cbe6c1;box-shadow:0 18px 40px rgba(63,154,57,.16);}
.bx-node-circle{flex:none;position:relative;width:60px;height:60px;margin-bottom:18px;border-radius:50%;display:grid;place-items:center;background:linear-gradient(150deg,#a6d196,#86c473);box-shadow:0 8px 18px rgba(63,154,57,.2);transition:transform .55s cubic-bezier(.16,.8,.3,1),box-shadow .55s,background .55s;}
.bx-hcard.active .bx-node-circle{background:linear-gradient(150deg,#6cba5b,#3f9a39);transform:scale(1.07);box-shadow:0 14px 26px rgba(63,154,57,.42),0 0 0 7px rgba(92,176,78,.16);}
.bx-hcard:hover .bx-node-circle{transform:scale(1.05);}
.bx-node-badge{position:absolute;top:-4px;left:-4px;width:25px;height:25px;border-radius:50%;background:#1b3a28;color:#fff;font-family:'Rubik';font-weight:700;font-size:12.5px;display:grid;place-items:center;border:3px solid #f7f2e8;transition:background .4s;}
.bx-hcard.active .bx-node-badge{background:#3f9a39;}
.bx-hcard-text{flex:1;}
.bx-hcard-title{font-family:'Rubik';font-weight:700;font-size:18px;color:#1b3a28;margin:0 0 7px;}
.bx-hcard-desc{font-size:14.5px;line-height:1.65;color:#6b776c;margin:0;}

/* ---------- יכולות ---------- */
.bx-feats{padding:34px 40px 96px;}
.bx-feats-head{text-align:center;max-width:680px;margin:0 auto 52px;}
.bx-feats-title{margin:0;font-family:'Rubik';font-weight:800;font-size:clamp(28px,3.6vw,42px);color:#1b3a28;letter-spacing:-.3px;}
.bx-feats-sub{margin:14px 0 0;font-size:16.5px;color:#6b776c;}
.bx-feats-grid{max-width:1120px;margin:0 auto;display:grid;grid-template-columns:repeat(3,1fr);gap:26px;}
.bx-feats-grid > .reveal{display:flex;}
.bx-feat{position:relative;flex:1;display:flex;flex-direction:column;align-items:flex-start;text-align:right;padding:28px 26px;}
.bx-feat:hover{transform:translateY(-5px);box-shadow:0 24px 46px rgba(70,60,35,.14);border-color:#dcebd2;}
.bx-feat-icon{width:48px;height:48px;border-radius:14px;display:grid;place-items:center;margin-bottom:18px;background:#e7f4e1;color:#2c5a3c;transition:background .4s,color .4s,transform .45s cubic-bezier(.16,.8,.3,1);}
.bx-feat:hover .bx-feat-icon{background:linear-gradient(150deg,#5cb04e,#3f9a39);color:#fff;transform:translateY(-2px);}
.bx-feat-title{font-family:'Rubik';font-weight:700;font-size:18px;color:#1b3a28;margin:0 0 8px;}
.bx-feat-desc{font-size:14.5px;line-height:1.65;color:#6b776c;margin:0;}
.bx-feat-soon{position:absolute;top:20px;left:20px;font-size:11.5px;font-weight:700;color:#3f9a39;background:#e7f4e1;border:1px solid #d2e8c9;padding:4px 11px;border-radius:999px;}

@media (max-width:900px){
  .bx-main{flex-direction:column;gap:38px;padding-top:20px;text-align:center;}
  .bx-col-text{max-width:560px;}
  .bx-lead-text{margin-inline:auto;}
}

/* ---------- תחומים (צבעוני + תמונות מונפשות) ---------- */
.bx-ind{padding:34px 40px 100px;}
.bx-ind-head{text-align:center;max-width:680px;margin:0 auto 52px;}
.bx-ind-title{margin:0;font-family:'Rubik';font-weight:800;font-size:clamp(28px,3.6vw,42px);color:#1b3a28;letter-spacing:-.3px;}
.bx-ind-sub{margin:14px 0 0;font-size:16.5px;color:#6b776c;}
.bx-ind-grid{max-width:1120px;margin:0 auto;display:flex;flex-wrap:wrap;justify-content:center;gap:26px;}
.bx-ind-grid > .reveal{display:flex;flex:0 1 330px;min-width:270px;max-width:350px;}
.bx-uc{flex:1;display:flex;flex-direction:column;padding:0;overflow:hidden;text-align:right;}
.bx-uc:hover{transform:translateY(-5px);box-shadow:0 24px 46px rgba(70,60,35,.14);border-color:#dcebd2;}
.bx-uc-img{position:relative;height:138px;overflow:hidden;display:grid;place-items:center;}
.bx-uc-img svg{width:74%;height:78%;position:relative;z-index:1;}
.bx-uc-shine{position:absolute;top:-30%;left:-60%;width:45%;height:160%;z-index:2;pointer-events:none;background:linear-gradient(90deg,transparent,rgba(255,255,255,.5),transparent);transform:rotate(18deg);animation:ucShine 6s ease-in-out infinite;}
@keyframes ucShine{0%{left:-60%}55%,100%{left:140%}}
.bx-uc-body{padding:20px 22px 24px;}
.bx-uc-title{font-family:'Rubik';font-weight:700;font-size:17.5px;margin:0 0 7px;}
.bx-uc-desc{font-size:14px;line-height:1.6;color:#6b776c;margin:0;}

/* ערכות צבע לתמונות */
.bx-uc-mint{background:linear-gradient(150deg,#e6f7f1,#cdeee1);color:#1f9d86;}
.bx-uc-rose{background:linear-gradient(150deg,#fdeef3,#f8dbe6);color:#d65b86;}
.bx-uc-blue{background:linear-gradient(150deg,#e9f1fd,#d4e5fb);color:#3a6fc0;}
.bx-uc-amber{background:linear-gradient(150deg,#fdf3e4,#f9e2c2);color:#cf8a26;}
.bx-uc-violet{background:linear-gradient(150deg,#f1ecfb,#e2d6f7);color:#7458c4;}
.bx-th-mint .bx-uc-title{color:#1f9d86;}
.bx-th-rose .bx-uc-title{color:#d65b86;}
.bx-th-blue .bx-uc-title{color:#3a6fc0;}
.bx-th-amber .bx-uc-title{color:#cf8a26;}
.bx-th-violet .bx-uc-title{color:#7458c4;}

/* אנימציות לתמונות */
.bx-flo{animation:ucFlo 4.5s ease-in-out infinite;}
.bx-flo2{animation:ucFlo 5.2s ease-in-out infinite reverse;}
@keyframes ucFlo{0%,100%{transform:translateY(0)}50%{transform:translateY(-6px)}}
.bx-beat{animation:ucBeat 2.6s ease-in-out infinite;}
@keyframes ucBeat{0%,100%{transform:scale(1)}18%{transform:scale(1.12)}30%{transform:scale(1)}45%{transform:scale(1.07)}60%{transform:scale(1)}}
.bx-draw{stroke-dasharray:180;stroke-dashoffset:180;animation:ucDraw 2.6s ease-in-out infinite;}
@keyframes ucDraw{0%{stroke-dashoffset:180;opacity:.25}45%{opacity:1}70%,100%{stroke-dashoffset:0;opacity:1}}
.bx-spin{animation:ucSpin 9s linear infinite;}
@keyframes ucSpin{to{transform:rotate(360deg)}}
.bx-sway{animation:ucSway 4s ease-in-out infinite;}
@keyframes ucSway{0%,100%{transform:rotate(-6deg)}50%{transform:rotate(6deg)}}
.bx-twk{animation:ucTwk 2.4s ease-in-out infinite;}
.bx-twk2{animation:ucTwk 2.4s ease-in-out infinite .8s;}
@keyframes ucTwk{0%,100%{opacity:.35;transform:scale(.82)}50%{opacity:1;transform:scale(1)}}
.bx-glow{animation:ucGlow 3s ease-in-out infinite;}
@keyframes ucGlow{0%,100%{opacity:.12;transform:scale(.92)}50%{opacity:.3;transform:scale(1.05)}}

/* ---------- מסלולים (Pricing) ---------- */
.bx-pricing{padding:34px 40px 16px;}
.bx-pricing-head{text-align:center;max-width:640px;margin:0 auto 50px;}
.bx-pricing-title{margin:0;font-family:'Rubik';font-weight:800;font-size:clamp(28px,3.6vw,42px);color:#1b3a28;letter-spacing:-.3px;}
.bx-pricing-sub{margin:14px 0 0;font-size:16.5px;color:#6b776c;}
.bx-pricing-grid{max-width:1080px;margin:0 auto;display:grid;grid-template-columns:repeat(3,1fr);gap:24px;align-items:stretch;}
.bx-pricing-grid > .reveal{display:flex;}
.bx-plan{flex:1;display:flex;flex-direction:column;padding:30px 28px;text-align:right;}
.bx-plan-pop{border:2px solid #3f9a39;box-shadow:0 22px 50px rgba(63,154,57,.20);transform:translateY(-10px);}
.bx-plan-top{display:flex;align-items:center;justify-content:space-between;gap:8px;min-height:30px;}
.bx-plan-name{margin:0;font-family:'Rubik';font-weight:800;font-size:21px;color:#1b3a28;}
.bx-plan-badge{background:#e7f4e1;color:#3f9a39;font-weight:700;font-size:12px;padding:5px 12px;border-radius:999px;white-space:nowrap;}
.bx-plan-price{display:flex;align-items:baseline;gap:7px;margin-top:16px;padding-bottom:22px;border-bottom:1px solid #eadfce;}
.bx-plan-amt{font-family:'Rubik';font-weight:800;font-size:clamp(34px,3.3vw,44px);color:#1b3a28;direction:ltr;}
.bx-plan-per{font-size:14px;color:#8a958b;font-weight:600;}
.bx-plan-feats{list-style:none;margin:22px 0;padding:0;display:flex;flex-direction:column;gap:13px;flex:1;}
.bx-plan-feats li{display:flex;align-items:flex-start;gap:9px;font-size:14.5px;color:#46524a;line-height:1.5;}
.bx-plan-feats svg{flex:none;margin-top:1px;}
.bx-plan-cta{margin-top:auto;display:block;text-align:center;font-family:'Rubik';font-weight:700;font-size:15.5px;padding:13px;border-radius:13px;text-decoration:none;border:1.5px solid #d3cdbd;color:#2c5a3c;background:transparent;transition:transform .2s,box-shadow .2s,background .2s,border-color .2s;}
.bx-plan-cta:hover{border-color:#bcd9b8;background:rgba(63,154,57,.06);}
.bx-plan-cta.pop{background:linear-gradient(145deg,#58af4c,#3f9a39);color:#fff;border-color:transparent;box-shadow:0 12px 26px rgba(63,154,57,.3);}
.bx-plan-cta.pop:hover{transform:translateY(-2px);box-shadow:0 18px 36px rgba(63,154,57,.44);}

/* ---------- שאלות נפוצות (FAQ) ---------- */
.bx-faq{padding:8px 40px 96px;}
.bx-faq-head{text-align:center;margin:0 auto 30px;}
.bx-faq-title{margin:0;font-family:'Rubik';font-weight:800;font-size:clamp(28px,3.6vw,42px);color:#1b3a28;letter-spacing:-.3px;}
.bx-faq-list{max-width:820px;margin:0 auto;display:flex;flex-direction:column;gap:14px;}
.bx-faq-list > .reveal{display:block;}
.bx-faq-item{padding:0;overflow:hidden;}
.bx-faq-item.open{border-color:#cbe6c1;box-shadow:0 14px 32px rgba(63,154,57,.12);}
.bx-faq-q{width:100%;background:transparent;border:none;cursor:pointer;display:flex;align-items:center;justify-content:space-between;gap:14px;padding:20px 26px;text-align:right;font-family:'Rubik';font-weight:700;font-size:17px;color:#1b3a28;}
.bx-faq-q span{flex:1;}
.bx-faq-chev{flex:none;transition:transform .35s cubic-bezier(.16,.8,.3,1);}
.bx-faq-item.open .bx-faq-chev{transform:rotate(180deg);}
.bx-faq-a-wrap{display:grid;grid-template-rows:0fr;transition:grid-template-rows .4s cubic-bezier(.16,.8,.3,1);}
.bx-faq-item.open .bx-faq-a-wrap{grid-template-rows:1fr;}
.bx-faq-a{overflow:hidden;}
.bx-faq-a p{margin:0;padding:0 26px 22px;font-size:15px;line-height:1.75;color:#5e6b62;}

/* ---------- CTA סופי + פוטר ---------- */
.bx-cta-band{position:relative;overflow:hidden;background:linear-gradient(135deg,#5cb04e 0%,#3f9a39 58%,#34882f 100%);padding:84px 40px;text-align:center;}
.bx-cta-deco{position:absolute;border-radius:50%;background:rgba(255,255,255,.09);z-index:1;pointer-events:none;}
.bx-cta-inner{position:relative;z-index:2;max-width:680px;margin:0 auto;}
.bx-cta-band h2{margin:0;font-family:'Rubik';font-weight:800;font-size:clamp(30px,4vw,46px);color:#fff;letter-spacing:-.3px;}
.bx-cta-band p{margin:16px 0 0;font-size:17px;color:rgba(255,255,255,.92);line-height:1.6;}
.bx-cta-white{display:inline-flex;margin-top:32px;align-items:center;gap:9px;font-family:'Rubik';font-weight:700;font-size:16.5px;color:#2f7a2a;background:#fff;padding:15px 34px;border-radius:14px;text-decoration:none;box-shadow:0 16px 36px rgba(20,40,15,.22);transition:transform .22s,box-shadow .22s;}
.bx-cta-white:hover{transform:translateY(-3px);box-shadow:0 24px 48px rgba(20,40,15,.3);}

.bx-footer{background:#f1ede2;border-top:1px solid #e7e0d2;padding:34px 40px 26px;}
.bx-footer-inner{max-width:1120px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;gap:22px;flex-wrap:wrap;}
.bx-footer-brand{display:flex;align-items:center;gap:11px;}
.bx-footer-name{display:flex;flex-direction:column;line-height:1.05;}
.bx-footer-name strong{font-family:'Rubik';font-weight:800;font-size:18px;color:#1b3a28;}
.bx-footer-name small{font-size:11.5px;color:#7c8a7f;}
.bx-footer-links{display:flex;gap:24px;flex-wrap:wrap;}
.bx-footer-links a{font-size:14px;color:#6b776c;text-decoration:none;transition:color .2s;}
.bx-footer-links a:hover{color:#3f9a39;}
.bx-footer-bottom{max-width:1120px;margin:22px auto 0;padding-top:18px;border-top:1px solid #e7e0d2;text-align:center;font-size:13px;color:#8a958b;}

@media (max-width:960px){
  .bx-hiw-grid,.bx-feats-grid{grid-template-columns:repeat(2,1fr);}
}
@media (max-width:720px){
  .bx-stats{padding:36px 16px 14px;}
  .bx-grid4{gap:10px;}
  .bx-stat-box{padding:22px 8px;}
  .bx-stat-num{font-size:clamp(22px,7vw,40px);}
  .bx-stat-label{font-size:11px;margin-top:10px;}
  .bx-hiw{padding:30px 16px 56px;}
  .bx-hiw-grid{gap:16px;}
  .bx-hcard{padding:22px 20px;}
  .bx-node-circle{width:54px;height:54px;margin-bottom:14px;}
  .bx-node-circle svg{width:24px;height:24px;}
  .bx-hcard-title{font-size:16px;}
  .bx-hcard-desc{font-size:13.5px;}
  .bx-feats{padding:24px 16px 72px;}
  .bx-feat{padding:22px 20px;}
}
@media (max-width:880px){
  .bx-pricing-grid{grid-template-columns:1fr;max-width:430px;}
  .bx-plan-pop{transform:none;}
}
@media (max-width:600px){
  .bx-hiw-grid,.bx-feats-grid{grid-template-columns:1fr;}
  .bx-footer-inner{flex-direction:column;align-items:center;text-align:center;gap:18px;}
  .bx-cta-band{padding:64px 24px;}
}
@media (prefers-reduced-motion:reduce){
  .reveal{opacity:1!important;transform:none!important;transition:none!important;}
  .bx-escape-bob,.bx-chev,.bx-escape-arrow{animation:none!important;}
  .bx-flo,.bx-flo2,.bx-beat,.bx-draw,.bx-spin,.bx-sway,.bx-twk,.bx-twk2,.bx-glow,.bx-uc-shine{animation:none!important;}
  .bx-msg-anim{animation:none!important;}
  .bx-escape-anim{animation:none!important;opacity:1!important;transform:translateX(-50%)!important;}
}
`
