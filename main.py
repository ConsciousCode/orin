import asyncio
import sys

from system import start
from tool import Create, Destroy, Subscribe, Unsubscribe, Publish

# Automatically links names to agent types
import agent

DBPATH = "private/system.db"

async def main(argv):
    try:
        await start(DBPATH, {
            tool.__name__.lower(): tool
            for tool in (Create, Destroy, Subscribe, Unsubscribe, Publish)
        })
    
    finally:
        print(flush=True)

if __name__ == "__main__":
    asyncio.run(main(sys.argv))