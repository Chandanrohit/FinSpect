"""Local FastAPI boundary for Gnani voice services used by the Streamlit UI."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from finspect.gnani_voice import (
    MAX_AUDIO_BYTES,
    GnaniAPIError,
    GnaniVoiceClient,
    validate_wav_audio,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def configured_gnani_key() -> str | None:
    """Load the shared key server-side from env or Streamlit's local secrets."""
    env_value = os.getenv("GNANI_API_KEY_ID", "").strip()
    if env_value:
        return env_value
    secrets_path = PROJECT_ROOT / ".streamlit" / "secrets.toml"
    try:
        with secrets_path.open("rb") as secrets_file:
            value = tomllib.load(secrets_file).get("GNANI_API_KEY_ID", "")
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


class SynthesisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def create_app(
    *,
    key_provider: Callable[[], str | None] = configured_gnani_key,
    client_factory: Callable[[str], GnaniVoiceClient] = GnaniVoiceClient,
) -> FastAPI:
    app = FastAPI(
        title="FinSpect local voice service",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def block_non_local_browser_origins(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme != "http" or (parsed.hostname or "").lower() not in {
                "localhost",
                "127.0.0.1",
                "::1",
            }:
                return Response(
                    content='{"detail":"Voice API accepts local browser requests only."}',
                    status_code=403,
                    media_type="application/json",
                )
        return await call_next(request)

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"status": "ok", "gnani_configured": bool(key_provider())}

    @app.post("/api/voice/transcribe")
    async def transcribe(
        audio_file: UploadFile = File(...),
        language_code: str = Form(...),
    ) -> dict[str, str]:
        key = key_provider()
        if not key:
            raise HTTPException(
                status_code=503,
                detail="Gnani is not configured. Set GNANI_API_KEY_ID in the server environment or local secrets file.",
            )

        audio = await audio_file.read(MAX_AUDIO_BYTES + 1)
        if len(audio) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="Audio exceeds FinSpect's 20 MB upload limit.")
        filename = Path(audio_file.filename or "question.wav").name
        if not filename.lower().endswith(".wav"):
            raise HTTPException(status_code=415, detail="Streamlit voice recording must be WAV audio.")

        try:
            validate_wav_audio(audio)
            transcript = client_factory(key).transcribe(
                audio,
                filename=filename,
                language_code=language_code,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except GnaniAPIError as exc:
            raise _safe_upstream_error(exc) from None
        return {"transcript": transcript}

    @app.post("/api/voice/synthesize")
    def synthesize(request: SynthesisRequest) -> Response:
        key = key_provider()
        if not key:
            raise HTTPException(
                status_code=503,
                detail="Gnani is not configured. Set GNANI_API_KEY_ID in the server environment or local secrets file.",
            )
        try:
            audio = client_factory(key).synthesize(request.text)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except GnaniAPIError as exc:
            raise _safe_upstream_error(exc) from None
        return Response(content=audio, media_type="audio/wav")

    return app


def _safe_upstream_error(error: GnaniAPIError) -> HTTPException:
    detail = {
        "message": str(error),
        "upstream_status": error.status_code,
        "category": error.category,
        "request_id": error.request_id,
    }
    return HTTPException(status_code=502, detail=detail)


app = create_app()
