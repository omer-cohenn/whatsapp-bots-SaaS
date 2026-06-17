import LegalPage from './LegalPage'

export default function PrivacyPage() {
  return (
    <LegalPage title="מדיניות פרטיות">
      <section aria-labelledby="privacy-intro">
        <h2 id="privacy-intro" className="text-lg font-bold text-slate-900">
          1. איזה מידע נאסף
        </h2>
        <p>
          אנו אוספים את פרטי החשבון הבסיסיים (שם, כתובת אימייל ותמונת פרופיל מחשבון
          Google), וכן נתונים הקשורים להפעלת הבוט עבור העסק שלכם. הטקסט שלהלן הוא
          טיוטה ראשונית למילוי בהמשך.
        </p>
      </section>

      <section aria-labelledby="privacy-use">
        <h2 id="privacy-use" className="text-lg font-bold text-slate-900">
          2. כיצד נעשה שימוש במידע
        </h2>
        <p>
          המידע משמש להפעלת השירות בלבד. נתונים רגישים, לרבות פרטי לידים ופרטי חיבור
          וואטסאפ, מאוחסנים מוצפנים, ומבודלים לפי עסק.
        </p>
      </section>

      <section aria-labelledby="privacy-rights">
        <h2 id="privacy-rights" className="text-lg font-bold text-slate-900">
          3. הזכויות שלכם
        </h2>
        <p>
          תוכלו לבקש בכל עת לעיין בנתונים שלכם, לתקן אותם או למחוק אותם, בכפוף לדין
          החל.
        </p>
      </section>
    </LegalPage>
  )
}
