"""Internal API /api/otp: latest-code lookup and TOTP."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from mockpost.request_ctx import get_test_id
from mockpost.otp import generate_totp_secret, get_latest_otp, get_totp_code

router = APIRouter(prefix="/api/otp", tags=["api"])


class TotpGen(BaseModel):
    identifier: str


@router.get("/latest")
async def api_latest_otp(request: Request, identifier: str, channel: str = "any"):
    test_id = get_test_id(request)
    otp = await get_latest_otp(identifier, channel, test_id)
    return otp or {"error": "not_found", "identifier": identifier}


@router.post("/totp/generate")
async def api_generate_totp(payload: TotpGen):
    return await generate_totp_secret(payload.identifier)


@router.get("/totp/code")
async def api_totp_code(identifier: str):
    code = await get_totp_code(identifier)
    return code or {"error": "not_found", "identifier": identifier}
