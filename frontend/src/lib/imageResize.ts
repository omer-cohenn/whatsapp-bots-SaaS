// Client-side downscale for gallery uploads (M20).
//
// The server caps a gallery image at 5MB and stores the file as-is on disk, so a
// straight-from-the-phone photo (often 4–8MB) either gets rejected or spends a
// long time on a mobile connection. We shrink it in the browser FIRST: the
// upload is smaller, faster, and much less likely to hit the 413.
//
// Deliberately narrow: we only touch LARGE `image/jpeg` files. PNG and WEBP pass
// through untouched, because re-encoding them to JPEG would flatten transparency
// to black — a nasty surprise on a logo-like image. Phone cameras produce JPEG,
// which is the case that actually needs this.
//
// This is a convenience, never a check. The server sniffs the real type from the
// bytes and enforces the size and the 40-image cap itself.

/** Long-edge cap for the resized image — plenty for a full-width gallery photo. */
const MAX_EDGE = 1600
/** Below this we leave the file completely alone. */
const RESIZE_ABOVE_BYTES = 1_500_000
/** JPEG quality for the re-encode. */
const QUALITY = 0.85

/** Decode a File into a loaded <img> via an object URL (revoked either way). */
function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      URL.revokeObjectURL(url)
      resolve(img)
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('פענוח התמונה נכשל.'))
    }
    img.src = url
  })
}

/** Promise wrapper around canvas.toBlob (which is callback-based). */
function canvasToBlob(canvas: HTMLCanvasElement, quality: number): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality))
}

/**
 * Return a smaller version of `file`, or the original when shrinking it would
 * not help (small file, not a JPEG, or the browser refused to encode).
 *
 * NEVER throws: a failure here just means we upload the original and let the
 * server have the final word. A resize hiccup must not block the owner.
 */
export async function shrinkImageForUpload(file: File): Promise<File> {
  if (file.type !== 'image/jpeg' || file.size <= RESIZE_ABOVE_BYTES) return file

  try {
    const img = await loadImage(file)
    const { naturalWidth: width, naturalHeight: height } = img
    if (!width || !height) return file

    // Never upscale — a 900px photo that happens to be heavy stays 900px.
    const scale = Math.min(1, MAX_EDGE / Math.max(width, height))
    if (scale === 1 && file.size <= RESIZE_ABOVE_BYTES) return file

    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(width * scale))
    canvas.height = Math.max(1, Math.round(height * scale))
    const ctx = canvas.getContext('2d')
    if (!ctx) return file
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height)

    const blob = await canvasToBlob(canvas, QUALITY)
    // Re-encoding can occasionally come out bigger; keep whichever is smaller.
    if (!blob || blob.size >= file.size) return file

    // The name is cosmetic — the server throws it away and generates a uuid.
    return new File([blob], 'photo.jpg', { type: 'image/jpeg' })
  } catch {
    return file
  }
}
