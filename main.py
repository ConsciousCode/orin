import asyncio
import sys
import

from system import Entry

DBPATH = "private/system.db"

async def main(argv):
    argv[]
    try:
        async with asyncio.TaskGroup() as tg:
            entry = Entry(DBPATH, {
                tool.__name__.lower(): tool
                for tool in (Create, Destroy, Subscribe, Unsubscribe, Publish)
            })
            tg.create_task(entry.start([
                Create, Destroy, Subscribe, Unsubscribe, Publish
            ]))
    
    except asyncio.CancelledError as e:
        print("Cancelled?", str(e))
        raise
    
    finally:
        print("Finally", flush=True)

if __name__ == "__main__":
    asyncio.run(main(sys.argv))