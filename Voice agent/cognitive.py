import json
import logging
from typing import AsyncIterator

import httpx

from config import get_settings

logger = logging.getLogger('hermex.voice.cognitive')


class CognitiveCoreError(RuntimeError):
    pass


class CognitiveCore:
    """Small, isolated adapter to the existing Hermes OpenAI-compatible endpoint.

    The voice layer never calls OmniRoute directly. Hermes remains responsible for
    model routing, tools, memory, planning, and agent behavior.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.timeout = httpx.Timeout(connect=10.0, read=120.0, write=20.0, pool=10.0)

    async def stream_reply(self, messages: list[dict], *, session_id: str) -> AsyncIterator[str]:
        headers = {'Accept': 'text/event-stream'}
        if self.settings.hermes_cognitive_api_key:
            headers['Authorization'] = f'Bearer {self.settings.hermes_cognitive_api_key}'

        payload = {
            'model': self.settings.hermes_cognitive_model,
            'messages': messages,
            'stream': True,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    'POST',
                    self.settings.hermes_cognitive_url,
                    headers=headers,
                    json=payload,
                ) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
                        raise CognitiveCoreError(
                            f'Cognitive Core returned HTTP {response.status_code}: {body[:500]!r}'
                        )

                    async for line in response.aiter_lines():
                        if not line.startswith('data:'):
                            continue
                        data = line[5:].strip()
                        if not data or data == '[DONE]':
                            continue
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError:
                            continue

                        choices = event.get('choices') or []
                        if not choices:
                            continue
                        delta = choices[0].get('delta') or {}
                        text = delta.get('content')
                        if text:
                            yield text
        except httpx.HTTPError as exc:
            logger.exception('Cognitive Core request failed for session %s', session_id)
            raise CognitiveCoreError('Unable to reach the Hermex Cognitive Core') from exc
