// Build a wa.me chat link from a lead's phone number.
//
// WhatsApp's click-to-chat URL wants an international number with NO plus / no
// punctuation (e.g. 972521234567). Israeli numbers are usually stored with a
// leading 0 (0521234567); we strip non-digits and swap that leading 0 for 972.
// Returns null when there's no usable number, so the caller can hide the button.

export function waLink(phone: string | null | undefined): string | null {
  if (!phone) return null
  let digits = phone.replace(/\D/g, '')
  if (!digits) return null
  // Local Israeli format (leading 0) → international (972).
  if (digits.startsWith('0')) {
    digits = `972${digits.slice(1)}`
  }
  return `https://wa.me/${digits}`
}
