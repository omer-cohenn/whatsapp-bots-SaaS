// Client-side image resize + compress. The app has NO external file storage, so
// the owner's service image is downscaled in the browser to a small, compressed
// `data:` URL and stored inline in services.image_url. This keeps the payload
// well under the backend's limit and avoids shipping multi-MB originals.
//
// Strategy: load the chosen file into an <img>, draw it onto a <canvas> scaled so
// the LONG edge is at most `maxEdge` (never upscales), then export JPEG. If the
// result is still too big, drop the quality and re-export until it fits.

/** Max pixels on the long edge of the resized image. */
const MAX_EDGE = 900
/** Target ceiling for the encoded data URL (characters). ~400KB. */
const MAX_DATA_URL_CHARS = 400_000
/** Starting JPEG quality, then we step down if the URL is too large. */
const START_QUALITY = 0.82
const MIN_QUALITY = 0.4
const QUALITY_STEP = 0.12

/** Read a File into a data: URL (used to feed the <img> element). */
function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(new Error('קריאת הקובץ נכשלה.'))
    reader.readAsDataURL(file)
  })
}

/** Decode a data: URL into a loaded HTMLImageElement. */
function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('פענוח התמונה נכשל.'))
    img.src = src
  })
}

/**
 * Resize + compress an image File to a small JPEG data URL.
 * - Keeps aspect ratio; the long edge is capped at MAX_EDGE (no upscaling).
 * - Re-encodes at decreasing quality until the URL fits MAX_DATA_URL_CHARS.
 * Throws (with a Hebrew message) if the file isn't an image or can't be decoded.
 */
export async function resizeImageToDataUrl(file: File): Promise<string> {
  if (!file.type.startsWith('image/')) {
    throw new Error('יש לבחור קובץ תמונה.')
  }

  const sourceUrl = await readFileAsDataUrl(file)
  const img = await loadImage(sourceUrl)

  const { width, height } = img
  if (!width || !height) throw new Error('פענוח התמונה נכשל.')

  const scale = Math.min(1, MAX_EDGE / Math.max(width, height))
  const targetW = Math.max(1, Math.round(width * scale))
  const targetH = Math.max(1, Math.round(height * scale))

  const canvas = document.createElement('canvas')
  canvas.width = targetW
  canvas.height = targetH
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('עיבוד התמונה נכשל.')
  ctx.drawImage(img, 0, 0, targetW, targetH)

  let quality = START_QUALITY
  let dataUrl = canvas.toDataURL('image/jpeg', quality)
  while (dataUrl.length > MAX_DATA_URL_CHARS && quality > MIN_QUALITY) {
    quality = Math.max(MIN_QUALITY, quality - QUALITY_STEP)
    dataUrl = canvas.toDataURL('image/jpeg', quality)
  }
  return dataUrl
}
