import LegalPage from './LegalPage'

export default function TermsPage() {
  return (
    <LegalPage title="תנאי שימוש">
      <section aria-labelledby="terms-intro">
        <h2 id="terms-intro" className="text-lg font-bold text-slate-900">
          1. כללי
        </h2>
        <p>
          תנאי שימוש אלו מסדירים את השימוש בפלטפורמת Bizz_up לניהול בוטים לוואטסאפ
          לעסקים. הטקסט שלהלן הוא טיוטה ראשונית למילוי בהמשך.
        </p>
      </section>

      <section aria-labelledby="terms-account">
        <h2 id="terms-account" className="text-lg font-bold text-slate-900">
          2. חשבון משתמש
        </h2>
        <p>
          ההתחברות מתבצעת באמצעות חשבון Google. כל עסק מקבל סביבה מבודלת ונפרדת,
          והנתונים אינם משותפים בין עסקים שונים.
        </p>
      </section>

      <section aria-labelledby="terms-usage">
        <h2 id="terms-usage" className="text-lg font-bold text-slate-900">
          3. שימוש מותר
        </h2>
        <p>
          השימוש בשירות כפוף לתנאי השימוש של וואטסאפ ולחוקים החלים. אין לעשות שימוש
          לרעה בשירות לצורך דיוור בלתי רצוי או תוכן אסור.
        </p>
      </section>
    </LegalPage>
  )
}
