import json
import logging

from dotenv import load_dotenv

from livekit.agents import Agent, AgentServer, AgentSession, JobContext, TurnHandlingOptions, cli, inference
from livekit.plugins import noise_cancellation, openai

from config import get_settings

load_dotenv()

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger('hermex.voice.agent')

# Original Hermex voice profiles mapped to currently supported LiveKit Inference
# voices. These are provider voice IDs, not AI model/provider controls exposed to users.
VOICE_MAP = {
    'rounded': 'Ashley',
    'glassy': 'Olivia',
    'calm': 'Odysseus',
    'warm': 'Ashley',
    'clear': 'Rex',
}

PACE_MAP = {
    'slow': 0.88,
    'normal': 1.00,
    'fast': 1.15,
}


class HermexVoiceAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="""
You are Hermex, a personal AI voice agent.

This is a voice-only interaction. Speak naturally, clearly, and concisely.
Never output markdown, code blocks, headings, bullet lists, JSON, or UI instructions
unless the user explicitly asks for spoken content that requires such formatting.
Do not describe the internal architecture, model provider, LiveKit, OmniRoute, or
voice pipeline unless the user explicitly asks about it.

Hermes is the Cognitive Core behind you. Use its reasoning, memory, tools, and
agentic capabilities through the configured OpenAI-compatible endpoint. Do not claim
to have performed an action unless the Cognitive Core actually returned evidence of it.

Interruptions are normal. If the user starts speaking while you are speaking, stop
cleanly and listen to the new turn. Prefer short natural sentences over long monologues.
""",
            allow_interruptions=True,
        )


def _tts_config(voice_profile: str, language: str, pace: str):
    voice = VOICE_MAP.get(voice_profile, VOICE_MAP['rounded'])
    rate = PACE_MAP.get(pace, PACE_MAP['normal'])
    # Inworld TTS 2 supports speaking_rate from 0.5 to 1.5 through LiveKit Inference.
    return inference.TTS(
        model='inworld/inworld-tts-2',
        voice=voice,
        language=language,
        extra_kwargs={'speaking_rate': rate, 'delivery_mode': 'BALANCED'},
    )


def _llm():
    if not settings.hermes_cognitive_url:
        raise RuntimeError('HERMES_COGNITIVE_URL is not configured')

    return openai.LLM(
        model=settings.hermes_cognitive_model,
        base_url=settings.hermes_cognitive_url,
        api_key=settings.hermes_cognitive_api_key or 'hermes-internal',
        temperature=0.7,
    )


server = AgentServer()


@server.rtc_session(agent_name=settings.livekit_agent_name)
async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {
        'room': ctx.room.name,
        'agent': settings.livekit_agent_name,
    }

    try:
        metadata = json.loads(ctx.job.metadata or '{}')
    except json.JSONDecodeError:
        logger.warning('Invalid job metadata, using defaults')
        metadata = {}

    session_id = str(metadata.get('session_id', 'unknown'))
    voice = str(metadata.get('voice', settings.hermex_default_voice))
    language = str(metadata.get('language', settings.hermex_default_language))
    pace = str(metadata.get('pace', settings.hermex_default_pace))

    if voice not in VOICE_MAP:
        voice = settings.hermex_default_voice
    if pace not in PACE_MAP:
        pace = settings.hermex_default_pace

    logger.info(
        'Starting Hermex voice session session_id=%s voice=%s language=%s pace=%s',
        session_id,
        voice,
        language,
        pace,
    )

    session = AgentSession(
        stt=inference.STT(model='deepgram/nova-3', language=language),
        llm=_llm(),
        tts=_tts_config(voice, language, pace),
        turn_handling=TurnHandlingOptions(
            turn_detection=inference.TurnDetector(),
        ),
        preemptive_generation=True,
    )

    agent = HermexVoiceAgent()

    await session.start(
        agent=agent,
        room=ctx.room,
        room_options={
            'audio_input': {
                'noise_cancellation': noise_cancellation.BVC(),
            }
        },
    )

    logger.info('Hermex voice session started session_id=%s', session_id)


if __name__ == '__main__':
    cli.run_app(server)
