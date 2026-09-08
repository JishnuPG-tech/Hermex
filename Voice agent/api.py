import json
import logging
import secrets
import uuid
from datetime import timedelta

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from livekit import api

from config import get_settings
from protocol import CreateSessionRequest, VoiceConfigResponse, VoiceSessionResponse, VoiceSettings

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger('hermex.voice.api')

app = FastAPI(title='Hermex Voice Agent API', version='1.0.0')

origins = settings.allowed_origins or ['*']
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=origins != ['*'],
    allow_methods=['GET', 'POST', 'OPTIONS'],
    allow_headers=['Authorization', 'Content-Type', 'X-Hermex-Voice-Secret'],
)

SUPPORTED_VOICES = ['rounded', 'glassy', 'calm', 'warm', 'clear']
SUPPORTED_LANGUAGES = ['en-US', 'en-GB', 'en-IN']
SUPPORTED_PACES = ['slow', 'normal', 'fast']


def _authorize(shared_secret: str | None) -> None:
    """Optional application-level protection for the token endpoint.

    LiveKit credentials are never exposed here. In production, configure a strong
    shared secret or replace this hook with the existing Hermex authentication layer.
    """
    configured = settings.voice_api_shared_secret
    if configured and not shared_secret:
        raise HTTPException(status_code=401, detail='Voice API authentication required')
    if configured and not secrets.compare_digest(shared_secret or '', configured):
        raise HTTPException(status_code=403, detail='Invalid voice API credentials')


def _validate_settings(request: CreateSessionRequest) -> VoiceSettings:
    if request.voice not in SUPPORTED_VOICES:
        raise HTTPException(status_code=400, detail='Unsupported voice')
    if request.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail='Unsupported language')
    if request.pace not in SUPPORTED_PACES:
        raise HTTPException(status_code=400, detail='Unsupported pace')
    return VoiceSettings(voice=request.voice, language=request.language, pace=request.pace)


@app.get('/health')
async def health() -> dict:
    return {'status': 'ok', 'service': 'hermex-voice-api', 'livekit_configured': bool(settings.livekit_url and settings.livekit_api_key and settings.livekit_api_secret)}


@app.get('/voice/config', response_model=VoiceConfigResponse)
async def voice_config() -> VoiceConfigResponse:
    return VoiceConfigResponse(
        agent_name=settings.livekit_agent_name,
        default_settings=VoiceSettings(
            voice=settings.hermex_default_voice,
            language=settings.hermex_default_language,
            pace=settings.hermex_default_pace,
        ),
        supported_voices=SUPPORTED_VOICES,
        supported_languages=SUPPORTED_LANGUAGES,
        supported_paces=SUPPORTED_PACES,
    )


@app.post('/voice/session', response_model=VoiceSessionResponse)
async def create_voice_session(
    request: CreateSessionRequest,
    x_hermex_voice_secret: str | None = Header(default=None),
) -> VoiceSessionResponse:
    _authorize(x_hermex_voice_secret)
    settings.validate_runtime()
    voice_settings = _validate_settings(request)

    # Opaque values are deliberate. LiveKit logs identities and room names, so no
    # user name, email, phone number, or other PII belongs in them.
    session_id = str(uuid.uuid4())
    room_name = f'hermex-voice-{session_id}'
    participant_identity = f'user-{uuid.uuid4()}'

    job_metadata = json.dumps({
        'session_id': session_id,
        'voice': voice_settings.voice,
        'language': voice_settings.language,
        'pace': voice_settings.pace,
    }, separators=(',', ':'))

    token = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(participant_identity)
        .with_name('Hermex User')
        .with_ttl(timedelta(seconds=settings.voice_token_ttl_seconds))
        .with_grants(api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        ))
        .with_room_config(api.RoomConfiguration(
            max_participants=2,
            agents=[api.RoomAgentDispatch(
                agent_name=settings.livekit_agent_name,
                metadata=job_metadata,
            )],
        ))
        .to_jwt()
    )

    logger.info('Created voice session %s', session_id)
    return VoiceSessionResponse(
        session_id=session_id,
        room_name=room_name,
        participant_identity=participant_identity,
        livekit_url=settings.livekit_url,
        token=token,
        token_expires_in=settings.voice_token_ttl_seconds,
        agent_name=settings.livekit_agent_name,
        settings=voice_settings,
    )
