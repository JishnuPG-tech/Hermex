from typing import Literal
from pydantic import BaseModel, Field

VoiceState = Literal['READY', 'CONNECTING', 'LISTENING', 'THINKING', 'SPEAKING', 'RECONNECTING', 'ERROR', 'DISCONNECTED']
VoicePace = Literal['slow', 'normal', 'fast']


class VoiceSettings(BaseModel):
    voice: str = Field(default='rounded', min_length=1, max_length=64)
    language: str = Field(default='en-GB', min_length=2, max_length=16)
    pace: VoicePace = 'normal'


class CreateSessionRequest(VoiceSettings):
    # Frontends may supply a stable application-level session identifier, but it is
    # never used directly as a LiveKit identity or room name.
    client_session_id: str | None = Field(default=None, max_length=128)


class VoiceSessionResponse(BaseModel):
    session_id: str
    room_name: str
    participant_identity: str
    livekit_url: str
    token: str
    token_expires_in: int
    agent_name: str
    settings: VoiceSettings


class VoiceConfigResponse(BaseModel):
    agent_name: str
    default_settings: VoiceSettings
    supported_voices: list[str]
    supported_languages: list[str]
    supported_paces: list[str]
