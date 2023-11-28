import asyncio
import sys

from src.system import start
from src.tool import Create, Destroy, Subscribe, Unsubscribe, Publish, Python, Shell

# Automatically links names to agent types
import src.agent

DBPATH = "private/system.db"

async def main(argv):
    try:
        await start(DBPATH, {
            tool.__name__.lower(): tool
            for tool in (Create, Destroy, Subscribe, Unsubscribe, Publish, Python, Shell)
        })
    
    finally:
        print(flush=True)

if __name__ == "__main__":
    asyncio.run(main(sys.argv))