// בורר פלטות הצבעים (M20) — בחירה עם תצוגה מקדימה של העמוד האמיתי
//
// Picking colours from swatches is guesswork. So the owner picks a palette and
// immediately sees THEIR OWN PAGE in it — not a sketch of it.
//
// 🔴 M20 revision. This file used to contain a hand-built `PagePreview`: a second,
// smaller implementation of the business page. It drifted from the real page and
// the owner caught it ("התצוגה מקדימה לא תואמת לאיך שהעמוד באמת נראה"). That
// component is gone. What renders below is <BusinessPageView> — literally the
// component the public route renders — scaled down inside <PagePreviewFrame>.
// There is now exactly one implementation of the page, so the preview cannot lie.
//
// Selection is a radiogroup, not a row of buttons: arrow keys move between
// palettes, which is both the correct semantics and the fastest way to flip
// through them and watch the preview change.
//
// The chosen palette is persisted as just its KEY inside `page_theme`
// (`{ palette: "ocean" }`). The backend stores that blob without interpreting
// it, so the colours themselves live only in `public/pageTheme.ts`.

import type { PublicService } from '../../../dashboard/appointmentTypes'
import type { BusinessPage, PageTheme } from '../../../dashboard/businessPageTypes'
import Icon from '../../ui/Icon'
import BookingFlow from '../BookingFlow'
import BusinessPageView from '../public/BusinessPageView'
import { PUBLIC_PAGE_CSS } from '../public/publicPageStyles'
// ONE palette table for the whole feature. It lives with the public page because
// that is where the colours actually render; the picker reads the same list so a
// swatch can never promise a look the visitor will not get.
import {
  PAGE_PALETTES,
  paletteVarsFor,
  resolvePalette,
  resolveRadius,
} from '../public/pageTheme'
import PagePreviewFrame from './PagePreviewFrame'

type Props = {
  theme: PageTheme
  /** Called with the palette key the owner picked; the parent persists it. */
  onSelect: (paletteId: string) => void
  /** The owner's real page — the preview renders this, not sample content. */
  page: BusinessPage
  /** The owner's real active services, so the preview's cards are theirs. */
  services: PublicService[]
  /** The owner's real welcome message. */
  welcomeMessage: string | null
  disabled?: boolean
}

export default function PalettePicker({
  theme,
  onSelect,
  page,
  services,
  welcomeMessage,
  disabled,
}: Props) {
  const selected = resolvePalette(theme)
  const radius = resolveRadius(theme)

  return (
    <div className="flex flex-col gap-4">
      <div
        role="radiogroup"
        aria-label="פלטת הצבעים של העמוד"
        className="grid grid-cols-2 gap-2 sm:grid-cols-4"
      >
        {PAGE_PALETTES.map((palette) => {
          const isSelected = palette.key === selected.key
          return (
            <button
              key={palette.key}
              type="button"
              role="radio"
              aria-checked={isSelected}
              disabled={disabled}
              onClick={() => onSelect(palette.key)}
              className={[
                'flex flex-col gap-2 rounded-xl border-2 p-2 text-start transition disabled:opacity-60',
                isSelected
                  ? 'border-leaf bg-leaf-soft'
                  : 'border-slate-200 hover:border-slate-300',
              ].join(' ')}
            >
              {/* Three stripes: page, card, brand — the actual colours, not labels. */}
              <span
                aria-hidden="true"
                className="flex h-8 overflow-hidden rounded-lg border border-black/10"
              >
                <span className="flex-1" style={{ background: palette.bg }} />
                <span className="flex-1" style={{ background: palette.surface }} />
                <span className="w-1/3" style={{ background: palette.primary }} />
              </span>
              <span className="flex items-center gap-1 text-xs font-medium text-slate-800">
                {isSelected ? (
                  <Icon name="check" size={14} className="text-leaf-ink" />
                ) : null}
                {palette.label}
              </span>
            </button>
          )
        })}
      </div>

      <div>
        <h3 className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-800">
          <Icon name="eye" size={16} className="text-leaf" />
          כך ייראה העמוד שלכם — זו התצוגה האמיתית, מוקטנת
        </h3>

        {/* The public page's own stylesheet, so the mosaic grid and the entry
            animation behave here exactly as they do on the live page. */}
        <style>{PUBLIC_PAGE_CSS}</style>

        <PagePreviewFrame themeVars={paletteVarsFor(selected, radius)}>
          <BusinessPageView page={page} interactive={false} animate={false}>
            <BookingFlow
              mode="preview"
              services={services}
              welcomeMessage={welcomeMessage}
            />
          </BusinessPageView>
        </PagePreviewFrame>
      </div>
    </div>
  )
}
