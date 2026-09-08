from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore', case_sensitive=False)

    livekit_url: str = Field(default='')
    livekit_api_key: str = Field(default='')
    livekit_api_secret: str = Field(default='')
    livekit_agent_name: str = 'hermex-voice'

    hermes_cognitive_url: str = 'http://127.0.0.1:8642/v1/chat/completions'
    hermes_cognitive_api_key: str = ''
    hermes_cognitive_model: str = 'hermes'

    hermex_default_voice: str = 'rounded'
    hermex_default_language: str = 'en-GB'
    hermex_default_pace: str = 'normal'

    voice_api_host: str = '0.0.0.0'
    voice_api_port: int = 8788
    voice_allowed_origins: str = ''
    voice_token_ttl_seconds: int = 600
    voice_session_ttl_seconds: int = 3600
    voice_api_shared_secret: str = ''

    log_level: str = 'INFO'

    @property
    def allowed_origins(self) -> list[str]:
        return [x.strip() for x in self.voice_allowed_origins.split(',') if x.strip()]

    def validate_runtime(self) -> None:
        missing = []
        if not self.livekit_url:
            missing.append('LIVEKIT_URL')
        if not self.livekit_api_key:
            missing.append('LIVEKIT_API_KEY')
        if not self.livekit_api_secret:
            missing.append('LIVEKIT_API_SECRET')
        if missing:
            raise RuntimeError('Missing required LiveKit configuration: ' + ', '.join(missing))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
