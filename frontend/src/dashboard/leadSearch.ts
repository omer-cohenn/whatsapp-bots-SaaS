// Client-side keyword search over leads.
//
// WHY CLIENT-SIDE: the fields an owner actually searches by — contact_name,
// phone, and every collected answer — are ENCRYPTED AT REST, so the database
// cannot do a LIKE over them. The browser, on the other hand, already holds the
// full DECRYPTED lead list (GET /api/leads returns it), so filtering the array
// in memory is both correct and instant.
//
// ⚠️ PYTHON TWIN — this rule is mirrored byte-for-byte in
//    `backend/app/services/leads/search.py` (`lead_matches`), which the
//    Excel-export endpoint uses to honour the same `q` the user typed.
//    ANY change here MUST be made there too, or an export will not match the
//    list the owner is looking at.

import { fileAnswers } from '../components/dashboard/AnswerValue'
import type { AnswerValue, Lead } from './types'

/** The one normalization used for BOTH the query and every searched field. */
function norm(value: string): string {
  return value.trim().toLowerCase()
}

/** Every searchable plain-text fragment carried by one answer value. */
function answerHaystack(value: AnswerValue): string[] {
  // A file answer contributes only its original file name (when it has one);
  // file_id / mime_type are machine data and are deliberately NOT searchable.
  const files = fileAnswers(value)
  if (files.length > 0) {
    return files
      .map((f) => f.name ?? '')
      .filter((name) => name !== '')
  }
  if (typeof value === 'string') return [value]
  return []
}

/**
 * Does `lead` match the free-text `query`?
 *
 * Rules (keep in sync with the Python twin):
 *  - the query is normalized with trim + lowercase; an EMPTY query matches
 *    everything (returns true).
 *  - the lead matches when the normalized query is a case-insensitive SUBSTRING
 *    of any of, each normalized the same way:
 *      * contact_name, phone, lead_name, outcome_note (null/undefined skipped)
 *      * every KEY of `answers`
 *      * every VALUE of `answers` — a string is itself, a file answer is its
 *        `name` (skipped when missing), an array is each element the same way.
 */
export function leadMatches(lead: Lead, query: string): boolean {
  const needle = norm(query)
  if (needle === '') return true

  const fields: (string | null | undefined)[] = [
    lead.contact_name,
    lead.phone,
    lead.lead_name,
    lead.outcome_note,
  ]
  for (const field of fields) {
    if (field == null) continue
    if (norm(field).includes(needle)) return true
  }

  for (const [key, value] of Object.entries(lead.answers ?? {})) {
    if (norm(key).includes(needle)) return true
    for (const fragment of answerHaystack(value)) {
      if (norm(fragment).includes(needle)) return true
    }
  }

  return false
}
