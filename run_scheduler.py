#!/usr/bin/env python3
"""Run the billing scheduler as a standalone service."""

import asyncio
import logging
import sys
import os

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from costlens.scheduler import BillingScheduler
from costlens.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def main():
    """Run the scheduler."""
    settings = get_settings()
    scheduler = BillingScheduler(settings)
    
    logging.info("Starting CostLens Billing Scheduler...")
    logging.info("Providers: %s", settings.enabled_providers)
    
    # Start scheduler (runs indefinitely)
    await scheduler.start(interval_hours=1, initial_sync=True)
    
    # Keep running
    try:
        while True:
            await asyncio.sleep(60)
    except KeyboardInterrupt:
        logging.info("Shutting down scheduler...")
        await scheduler.stop()

if __name__ == "__main__":
    asyncio.run(main())
