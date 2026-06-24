// רצועת CTA סופית + פוטר דף הנחיתה: קריאה לפעולה וקישורי תנאים/פרטיות/נגישות.

import { Link } from 'react-router-dom'
import Reveal from './Reveal'

export default function Footer() {
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
