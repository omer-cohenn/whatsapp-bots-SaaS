// Public accessibility statement, rendered inside the shared LegalPage wrapper
// (which carries the "draft — needs review" banner). Declares the conformance
// target, what is implemented, and how to report an accessibility problem.

import LegalPage from './LegalPage'

export default function AccessibilityPage() {
  return (
    <LegalPage title="הצהרת נגישות">
      <section aria-labelledby="a11y-commitment">
        <h2 id="a11y-commitment" className="text-lg font-bold text-slate-900">
          המחויבות שלנו לנגישות
        </h2>
        <p>
          ב-Bizz_up אנו רואים בנגישות ערך מרכזי. אנו פועלים כדי שכל אדם, לרבות
          אנשים עם מוגבלות, יוכל לעשות שימוש מלא ונוח בשירות, ומשקיעים מאמץ מתמשך
          בשיפור חוויית השימוש לכלל המשתמשים.
        </p>
      </section>

      <section aria-labelledby="a11y-standard">
        <h2 id="a11y-standard" className="text-lg font-bold text-slate-900">
          תקן הנגישות
        </h2>
        <p>
          אנו שואפים לעמוד בדרישות תקן ישראלי ת״י 5568 לנגישות תכנים באינטרנט,
          בהתאם להנחיות WCAG 2.1 ברמת תאימות AA.
        </p>
      </section>

      <section aria-labelledby="a11y-implemented">
        <h2 id="a11y-implemented" className="text-lg font-bold text-slate-900">
          מה יושם באתר
        </h2>
        <ul className="list-disc space-y-1 pe-6">
          <li>ניווט מלא באמצעות מקלדת</li>
          <li>תוויות ARIA לרכיבים אינטראקטיביים</li>
          <li>ניגודיות צבעים תקנית</li>
          <li>תמיכה מלאה בכיווניות מימין לשמאל (RTL)</li>
          <li>כיבוד העדפת הפחתת תנועה (prefers-reduced-motion)</li>
          <li>קישורי דילוג ישיר לתוכן</li>
        </ul>
      </section>

      <section aria-labelledby="a11y-contact">
        <h2 id="a11y-contact" className="text-lg font-bold text-slate-900">
          דיווח על בעיית נגישות
        </h2>
        <p>
          נתקלתם בקושי או בבעיית נגישות? נשמח לדעת ולתקן. ניתן לפנות לרכז הנגישות
          שלנו בכתובת{' '}
          <a
            href="mailto:accessibility@bizz-up.example"
            className="text-brand hover:underline"
          >
            accessibility@bizz-up.example
          </a>
          . בפנייתכם נסו לתאר את הבעיה, את הדף שבו היא הופיעה ואת סוג הדפדפן או
          הטכנולוגיה המסייעת שבה אתם משתמשים.
        </p>
        <p>רכז נגישות: צוות Bizz_up.</p>
      </section>

      <section aria-labelledby="a11y-updated">
        <h2 id="a11y-updated" className="text-lg font-bold text-slate-900">
          עדכון ההצהרה
        </h2>
        <p>עודכן לאחרונה: יוני 2026.</p>
      </section>
    </LegalPage>
  )
}
