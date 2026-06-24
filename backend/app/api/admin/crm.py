# בק‑אופיס מנהל — CRM מכירות: לוח שלבים, שינוי שלב, הוספת/קריאת הערות
"""Admin sales-CRM routes (M13): the platform-level sales pipeline.

The CRM tables (business_crm, crm_notes) have NO direct app_role grant — they are
reachable ONLY through these admin-gated SECURITY DEFINER functions. The two
writers stamp the admin's REAL identity (session user_id = the Google sub in
users(id), + email) for the FK + audit trail — never a client value. Note text is
never logged. Moved VERBATIM from the old single-file `admin.py` — no logic change.
"""

from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Path, Request, status

from app.api.admin._common import (
    _BUSINESS_ID_MAX,
    _iso,
    _parse_timestamp_or_422,
    log,
)
from app.core.deps import current_admin
from app.models.admin import (
    AdminCrmListResponse,
    AdminCrmNote,
    AdminCrmNoteCreatedResponse,
    AdminCrmNoteRequest,
    AdminCrmNotesResponse,
    AdminCrmRow,
    AdminCrmStageRequest,
    AdminCrmStageResponse,
)

router = APIRouter()


@router.get("/crm", response_model=AdminCrmListResponse)
async def admin_crm_list(request: Request) -> AdminCrmListResponse:
    """The sales pipeline board: every business as a card with its stage (SD).

    admin_crm_list returns every business once (stage defaults to 'new' when there
    is no CRM row), with the last-contacted / next-follow-up timestamps and the
    note count. Cross-tenant SD on a plain pool connection.
    """
    async with request.app.state.pg_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM admin_crm_list()")
    businesses = [
        AdminCrmRow(
            business_id=str(r["business_id"]),
            name=r["name"],
            plan_code=r["plan_code"],
            stage=r["stage"],
            last_contacted_at=_iso(r["last_contacted_at"]),
            next_followup_at=_iso(r["next_followup_at"]),
            note_count=int(r["note_count"]),
        )
        for r in rows
    ]
    return AdminCrmListResponse(businesses=businesses)


@router.patch(
    "/businesses/{business_id}/crm", response_model=AdminCrmStageResponse
)
async def admin_set_crm_stage(
    body: AdminCrmStageRequest,
    request: Request,
    business_id: str = Path(..., min_length=1, max_length=_BUSINESS_ID_MAX),
    admin: dict[str, str] = Depends(current_admin),
) -> AdminCrmStageResponse:
    """Move a business to a new sales stage (+ optional follow-up), and audit it.

    admin_set_crm_stage upserts business_crm.stage, sets next_followup_at, and
    writes an admin_audit row stamped with the REAL admin identity (admin['id'] =
    the session Google sub in users(id), + email) — never a client value.

    Error mapping (from the SD function's RAISE):
      * check_violation       → 422 (bad stage — also pre-gated by the Literal)
      * foreign_key_violation → 404 (unknown business)
    `next_followup` is an optional ISO-8601 timestamp; a bad value → 422.
    """
    next_followup = _parse_timestamp_or_422(body.next_followup, "next_followup")
    try:
        async with request.app.state.pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM admin_set_crm_stage($1, $2, $3, $4, $5)",
                admin["id"],
                admin["email"],
                business_id,
                body.stage,
                next_followup,
            )
    except asyncpg.exceptions.CheckViolationError:
        # The SD function rejected the stage (defense in depth behind the Literal).
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid stage",
        ) from None
    except asyncpg.exceptions.ForeignKeyViolationError:
        # Unknown business (the SD function raises foreign_key_violation). We do not
        # echo the message (no id leak).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="business not found"
        ) from None
    except asyncpg.exceptions.DataError:
        # A malformed business uuid never matches a business.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="business not found"
        ) from None

    log.info("admin set crm stage", extra={"business_id": str(row["business_id"])})
    return AdminCrmStageResponse(
        business_id=str(row["business_id"]),
        stage=row["stage"],
        next_followup_at=_iso(row["next_followup_at"]),
    )


@router.post(
    "/businesses/{business_id}/crm/notes",
    response_model=AdminCrmNoteCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def admin_add_crm_note(
    body: AdminCrmNoteRequest,
    request: Request,
    business_id: str = Path(..., min_length=1, max_length=_BUSINESS_ID_MAX),
    admin: dict[str, str] = Depends(current_admin),
) -> AdminCrmNoteCreatedResponse:
    """Append a sales note to a business's CRM log (admin_add_crm_note).

    The note is stamped with the REAL admin identity (admin['id'] = the session
    Google sub in users(id), + email) — never a client value. The note text is
    NEVER logged (owner-business sales data).

    Error mapping:
      * check_violation       → 422 (blank note — also pre-gated by min_length)
      * foreign_key_violation → 404 (unknown business)
    """
    try:
        async with request.app.state.pg_pool.acquire() as conn:
            note_id = await conn.fetchval(
                "SELECT admin_add_crm_note($1, $2, $3, $4)",
                admin["id"],
                admin["email"],
                business_id,
                body.note,
            )
    except asyncpg.exceptions.CheckViolationError:
        # Blank note (defense in depth behind the Pydantic min_length).
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="note must not be blank",
        ) from None
    except asyncpg.exceptions.ForeignKeyViolationError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="business not found"
        ) from None
    except asyncpg.exceptions.DataError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="business not found"
        ) from None

    log.info("admin add crm note", extra={"business_id": business_id})
    return AdminCrmNoteCreatedResponse(note_id=str(note_id))


@router.get(
    "/businesses/{business_id}/crm/notes", response_model=AdminCrmNotesResponse
)
async def admin_crm_notes(
    request: Request,
    business_id: str = Path(..., min_length=1, max_length=_BUSINESS_ID_MAX),
) -> AdminCrmNotesResponse:
    """A business's CRM note log, newest first (admin_crm_notes).

    A malformed/unknown business id simply yields an empty log (the SD function
    matches no notes). The note text is part of the response (it is owner-business
    sales context, shown only to the admin) but is NEVER logged here.
    """
    try:
        async with request.app.state.pg_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, admin_email, note, created_at FROM admin_crm_notes($1)",
                business_id,
            )
    except asyncpg.exceptions.DataError:
        # A malformed uuid never matches notes → an empty log (not a 404).
        return AdminCrmNotesResponse(notes=[])
    notes = [
        AdminCrmNote(
            id=str(r["id"]),
            admin_email=r["admin_email"],
            note=r["note"],
            created_at=_iso(r["created_at"]),
        )
        for r in rows
    ]
    return AdminCrmNotesResponse(notes=notes)
