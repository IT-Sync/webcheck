import asyncio

from agent.client import AgentClient
from agent.config import load_config


async def main():
    config = load_config()
    print(
        "Starting Webcheck agent "
        f"{config.agent_id} ({config.country}"
        f"{', ' + config.region if config.region else ''})"
    )
    await AgentClient(config).run_forever()


if __name__ == "__main__":
    asyncio.run(main())
