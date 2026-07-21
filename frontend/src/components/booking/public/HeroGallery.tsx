// הגלריה היא ההירו — פסיפס תמונות ברוחב מלא בראש העמוד, שנפתח ל-lightbox.
//
// M20 revision: the owner asked for the photos to be the FIRST thing on the page
// ("התמונות אני רוצה שיהיו ממש בהירו"), like the reference's `mosaic-grid`. So
// this is no longer a section further down — `BusinessPageView` renders it at the
// very top, edge to edge, and the logo/name/address sit underneath it.
//
// Layout comes from `.bp-mosaic` in `publicPageStyles.ts`: five tiles on desktop,
// ONE tall tile on a phone. Collapsing on mobile hides tiles, not content — the
// "הצג את כל התמונות" button opens the lightbox, which pages through every photo
// including the ones the grid dropped.
//
// 🔴 This component is rendered by BOTH the public page and the owner's wizard
// preview. That is the point: the preview cannot drift from the page, because
// there is only one implementation. `interactive={false}` is the ONLY difference
// the preview gets — same elements, same classes, just not clickable.

import { useState } from 'react'
import type { PublicBusinessImage } from '../../../dashboard/businessPageTypes'
import { imageSrc } from '../../../dashboard/businessPageTypes'
import ImageLightbox, { galleryAlt } from './ImageLightbox'
import Icon from '../../ui/Icon'

type Props = {
  images: PublicBusinessImage[]
  businessName: string
  /** false in the wizard preview: tiles are inert and the lightbox never mounts. */
  interactive?: boolean
}

/** Tiles shown in the mosaic; the rest are reachable through the lightbox. */
const MOSAIC_SIZE = 5

export default function HeroGallery({ images, businessName, interactive = true }: Props) {
  // null = closed. Storing the index (not a boolean) keeps the dialog stateless.
  const [openIndex, setOpenIndex] = useState<number | null>(null)

  // No photos ⇒ no mosaic at all, rather than an empty frame.
  if (images.length === 0) return null

  const tiles = images.slice(0, MOSAIC_SIZE)

  return (
    <section aria-label="תמונות מהעסק" className="relative">
      <div className="bp-mosaic overflow-hidden rounded-[var(--bp-radius)]">
        {tiles.map((img, i) => (
          <button
            key={img.id}
            type="button"
            disabled={!interactive}
            onClick={() => setOpenIndex(i)}
            className={[
              'bp-tile',
              i === 0 ? 'bp-tile-main' : `bp-tile-${i}`,
              'group relative overflow-hidden bg-[color:var(--bp-border)]',
              'focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-inset focus-visible:ring-[color:var(--bp-primary)]',
            ].join(' ')}
          >
            <img
              src={imageSrc(img.storage_path)}
              alt={galleryAlt(img, i + 1, images.length, businessName)}
              loading={i === 0 ? 'eager' : 'lazy'}
              className="h-full w-full object-cover transition duration-500 group-hover:scale-105"
            />
          </button>
        ))}

        {/* LAYER 2 — the fog. Inside the mosaic's own rounded, overflow-hidden
            frame so it can never spill past the corners. See `.bp-fog`. */}
        <div className="bp-fog" aria-hidden="true" />
      </div>

      {/* Always rendered: on a phone it is the only route to photos 2..N. */}
      <button
        type="button"
        disabled={!interactive}
        onClick={() => setOpenIndex(0)}
        style={{
          backgroundColor: 'var(--bp-surface)',
          color: 'var(--bp-text)',
          borderColor: 'var(--bp-border)',
        }}
        className="absolute bottom-3 left-3 inline-flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-semibold shadow-lg transition hover:brightness-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--bp-primary)]"
      >
        <Icon name="photo" size={16} />
        {`הצג את כל התמונות (${images.length})`}
      </button>

      {interactive && openIndex !== null ? (
        <ImageLightbox
          images={images}
          index={openIndex}
          onIndexChange={setOpenIndex}
          onClose={() => setOpenIndex(null)}
          businessName={businessName}
        />
      ) : null}
    </section>
  )
}
