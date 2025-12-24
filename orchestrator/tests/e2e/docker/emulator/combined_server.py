"""Combined server for E2E testing.

Runs both:
- Emulator server (port 8080) - CPU load simulation
- Agent simulator (port 8085) - Agent install/verify/run

This simulates a target server that has both the CPU emulator
and a security agent installed.
"""

import asyncio
import os
import sys

import uvicorn


async def run_emulator():
    """Run emulator server."""
    from emulator_server import app as emulator_app

    port = int(os.getenv("EMULATOR_PORT", "8080"))
    config = uvicorn.Config(
        emulator_app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def run_agent():
    """Run agent simulator server."""
    from agent_simulator import agent_app

    port = int(os.getenv("AGENT_PORT", "8085"))
    config = uvicorn.Config(
        agent_app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    """Run both servers concurrently."""
    print("Starting combined server...")
    print(f"  Emulator: port {os.getenv('EMULATOR_PORT', '8080')}")
    print(f"  Agent:    port {os.getenv('AGENT_PORT', '8085')}")

    await asyncio.gather(
        run_emulator(),
        run_agent(),
    )


if __name__ == "__main__":
    asyncio.run(main())
