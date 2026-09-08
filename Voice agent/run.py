import asyncio
import logging
import os
import signal
import subprocess
import sys

import uvicorn

from config import get_settings

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger('hermex.voice.run')


def main() -> None:
    # Render's free web service model is HTTP-facing. Run the token API and the
    # LiveKit worker in one isolated container for the first deployment. They are
    # still separate processes and can later be split into independent services.
    agent = subprocess.Popen([sys.executable, 'agent.py', 'start'])

    def stop(*_args):
        if agent.poll() is None:
            agent.terminate()
            try:
                agent.wait(timeout=10)
            except subprocess.TimeoutExpired:
                agent.kill()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    try:
        uvicorn.run(
            'api:app',
            host=settings.voice_api_host,
            port=settings.voice_api_port,
            log_level=settings.log_level.lower(),
        )
    finally:
        stop()


if __name__ == '__main__':
    main()
