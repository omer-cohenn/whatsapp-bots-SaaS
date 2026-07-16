// נתוני דף הנחיתה (בוטיק): הודעות הצ'אט, שלבים, יכולות, תחומים, מסלולים ושאלות נפוצות.

export type ChatMessage = { side: 'user' | 'bot'; text: string; time?: string }

export const MESSAGES: ChatMessage[] = [
  { side: 'user', text: 'היי', time: '10:24' },
  { side: 'bot', text: 'ברוכים הבאים לעסק שלך! 👋 אני בוטיק, העוזר החכם שלך. במה אוכל לעזור לך היום?' },
  { side: 'bot', text: 'תן לנו לנהל לך את הוואטסאפ, ואתה תנהל את העסק שלך.' },
  { side: 'bot', text: 'תחסוך שעות יקרות של מענה ללקוחות בוואטסאפ.' },
]
export const ESCAPE_TEXT = 'אז למה אתה מחכה?'

export type Step = { n: number; key: string; title: string; desc: string }
export const STEPS: Step[] = [
  { n: 1, key: 'google', title: 'מתחברים עם Google', desc: 'חשבון ועסק נפתחים אוטומטית — בלי טפסים ארוכים.' },
  { n: 2, key: 'ai', title: 'בונים בוט עם עוזר ה-AI', desc: 'בשפה חופשית, בלי קוד — מתארים, והבוט נבנה.' },
  { n: 3, key: 'whatsapp', title: 'מחברים את הוואטסאפ', desc: 'סריקת QR מהירה — המספר הקיים של העסק.' },
  { n: 4, key: 'config', title: 'מגדירים יכולות', desc: 'לידים, תורים ומענה אנושי — בוחרים מה הבוט יעשה.' },
  { n: 5, key: 'live', title: 'עולים לאוויר', desc: 'הבוט מתחיל לענות ללקוחות 24/7, בלי התערבות.' },
  { n: 6, key: 'leads', title: 'מקבלים לידים ופגישות', desc: 'אוטומטית, ישר לדשבורד שלכם.' },
]

export type Feature = { key: string; title: string; desc: string; soon?: boolean }
export const FEATURES: Feature[] = [
  { key: 'leads', title: 'איסוף מידע', desc: 'שאלון חכם שאוסף את הפרטים החשובים — שמור ומוצפן.' },
  { key: 'calendar', title: 'קביעת תורים', desc: 'דף הזמנה לעסק, מסונכרן ליומן Google ולפגישות Meet.' },
  { key: 'handoff', title: 'מעבר לנציג אנושי', desc: 'הבוט מזהה צורך ומעביר לצ׳אט חי עם נציג מהצוות.' },
  { key: 'ai', title: 'בונה בוט עם AI', desc: 'מתארים בשפה חופשית — והעוזר בונה את הבוט בשבילכם.' },
  { key: 'dashboard', title: 'דשבורד מלא', desc: 'לידים, שיחות ופגישות — הכול במקום אחד וברור.' },
  { key: 'rag', title: 'מענה מידע מהעסק', desc: 'תשובות מדויקות מתוך הקבצים והאתר של העסק (RAG).', soon: true },
]

export type Industry = { key: string; theme: string; title: string; desc: string }
export const INDUSTRIES: Industry[] = [
  { key: 'health', theme: 'mint', title: 'קליניקות וטיפול', desc: 'תיאום פגישות ותזכורות ללקוחות.' },
  { key: 'beauty', theme: 'rose', title: 'מספרות וקוסמטיקה', desc: 'קביעת תורים ישירות בוואטסאפ.' },
  { key: 'insurance', theme: 'blue', title: 'סוכני ביטוח', desc: 'איסוף פרטים לפי מסלול ביטוח רצוי ואיסוף מידע במקרה של תביעות' },
  { key: 'service', theme: 'amber', title: 'נותני שירות ובעלי מקצוע', desc: 'הצעות מחיר וזימון קריאות שירות.' },
  { key: 'consult', theme: 'violet', title: 'יועצים ומאמנים', desc: 'מענה ראשוני וקביעת שיחות ייעוץ.' },
]

export type Plan = { name: string; amt: string; per: string; was?: string; note?: string; annual?: string; popular: boolean; feats: string[] }
export const PLANS: Plan[] = [
  { name: 'חינמי', amt: 'חינם', per: 'לתמיד', popular: false,
    feats: ['בניית בוט עם AI', 'מסלול שיחה אחד', '30 שיחות בחודש', 'מענה לעד 5 מספרי טלפון', 'מערכת לניהול לידים'] },
  { name: 'מקצועי', amt: '₪149', per: '/לחודש', was: '₪200', note: 'מחיר השקה לזמן מוגבל', annual: 'או ₪1,490 לשנה — חודשיים מתנה', popular: true,
    feats: ['כל מה שבחינם', 'עד 5 מסלולי שיחה', 'עד 600 שיחות בחודש', 'מספרי טלפון ללא הגבלה', 'דשבורד מלא'] },
  { name: 'עסקי', amt: '₪299', per: '/לחודש', was: '₪349', note: 'מחיר השקה לזמן מוגבל', annual: 'או ₪2,990 לשנה — חודשיים מתנה', popular: false,
    feats: ['כל מה שבמקצועי', 'קביעת וניהול פגישות + סנכרון Google Calendar ו-Meet', 'עד 9 מסלולי שיחה', 'עד 2,000 לידים בחודש'] },
]

export type FaqItem = { q: string; a: string }
export const FAQ: FaqItem[] = [
  { q: 'צריך לדעת לתכנת?', a: 'לא, בכלל לא. בונים את הבוט בשפה חופשית מול עוזר ה-AI — מתארים מה שצריך והוא מקים את הכול בשבילכם. בלי קוד ובלי הגדרות מסובכות.' },
  { q: 'צריך מספר וואטסאפ חדש?', a: 'לא. הבוט מתחבר למספר הוואטסאפ הקיים של העסק בסריקת QR פשוטה, כך שהלקוחות ממשיכים לכתוב בדיוק לאותו מספר שהם כבר מכירים.' },
  { q: 'הנתונים מאובטחים?', a: 'כן. כל הנתונים מוצפנים ונשמרים לפי תקני אבטחה מקובלים, ורק לכם יש אליהם גישה — דרך הדשבורד האישי שלכם.' },
  { q: 'כמה זמן לוקח להקים?', a: 'כ-10 דקות. מתחברים עם Google, בונים את הבוט בעזרת ה-AI ומחברים את הוואטסאפ — והבוט עולה לאוויר ומתחיל לענות ללקוחות מיד.' },
  
]
