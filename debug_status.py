import asyncio
import logging
from FactoryVerse.ui.service_manager import ServiceManager

# Configure logging to see internal errors
logging.basicConfig(level=logging.ERROR)


async def main():
    print("Initializing ServiceManager...")
    sm = ServiceManager()

    print("Getting statuses...")
    statuses = await sm.get_all_statuses()

    for status in statuses:
        print(f"--- {status.name} ---")
        print(f"Running: {status.running}")
        print(f"Text: {status.status_text}")
        print(f"Details: {status.details}")
        if "error" in status.details:
            print(f"ERROR DETAIL: {status.details['error']}")


if __name__ == "__main__":
    asyncio.run(main())
