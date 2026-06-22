// Public marketing landing page (shown to visitors who are NOT logged in).
// Composed from small section components. Semantic landmarks, a skip-link, and
// the shared <SiteFooter/> close it out. RTL Hebrew throughout.

import LandingHeader from '../components/landing/LandingHeader'
import Hero from '../components/landing/Hero'
import StatsStrip from '../components/landing/StatsStrip'
import HowItWorks from '../components/landing/HowItWorks'
import Features from '../components/landing/Features'
import UseCases from '../components/landing/UseCases'
import Pricing from '../components/landing/Pricing'
import Faq from '../components/landing/Faq'
import CtaSection from '../components/landing/CtaSection'
import SiteFooter from '../components/SiteFooter'

export default function LandingPage() {
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="skip-link">
        דלגו לתוכן
      </a>

      <LandingHeader />

      <main id="main" className="flex-1">
        <Hero />
        <StatsStrip />
        <HowItWorks />
        <Features />
        <UseCases />
        <Pricing />
        <Faq />
        <CtaSection />
      </main>

      <SiteFooter />
    </div>
  )
}
