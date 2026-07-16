// מקטע ה-Hero של דף הנחיתה: כותרת, טלפון עם הדמיית צ'אט וואטסאפ מונפש, ובועת "אז למה אתה מחכה?".

import { useEffect, useRef, useState } from 'react'
import { MESSAGES, ESCAPE_TEXT } from './data'

export default function HeroSection() {
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
          <img src="/botik-logo.png" alt="Botik" className="bx-logo-img" />
        </div>
        <a className="bx-nav-cta" href="/auth/google">התחברות</a>
      </header>

      <div className="bx-main">
        <div className="bx-col-text">
          <span className="bx-eyebrow">העוזר החכם לעסק שלך</span>
          <h1 className="bx-headline">
            הבוט שעונה ללקוחות, אוסף פרטים וקובע פגישות
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
