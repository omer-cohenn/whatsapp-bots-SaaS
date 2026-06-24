// דף נחיתה ציבורי (מבקרים לא מחוברים): מרכיב את מקטעי "בוטיק" לפי הסדר.
// Public marketing landing page (shown to visitors who are NOT logged in):
// Omer's "בוטיק" page. This single page is an approved exception to the
// "Tailwind only" rule — it carries its own embedded <style>{CSS}</style> block
// (the bx-* classes) kept 1:1 from the source design. RTL Hebrew throughout.
//
// Real links are wired to the existing routes:
//   - "התחברות" / every "התחילו" / "התחילו חינם" → /auth/google (backend OAuth start)
//   - footer links → /terms, /privacy, /accessibility (react-router)
//
// The visual sections live in src/components/landing/*; this page only composes
// them in the same order, with the shared CSS block. No copy/style/logic change.

import HeroSection from '../components/landing/HeroSection'
import StatsBand from '../components/landing/StatsBand'
import HowItWorks from '../components/landing/HowItWorks'
import FeaturesSection from '../components/landing/FeaturesSection'
import IndustriesSection from '../components/landing/IndustriesSection'
import PricingSection from '../components/landing/PricingSection'
import FaqSection from '../components/landing/FaqSection'
import Footer from '../components/landing/Footer'
import { CSS } from '../components/landing/styles'

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
