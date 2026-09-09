#!/usr/bin/env python3
"""Run the WeChat Work bot as a standalone service."""

import asyncio
import logging
import sys
import os

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from costlens.bot.wechat_work import WeChatWorkBot
from costlens.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def main():
    """Run the WeChat Work bot."""
    settings = get_settings()
    bot = WeChatWorkBot(settings)
    
    logging.info("Starting CostLens WeChat Work Bot...")
    
    # Start bot (runs indefinitely)
    await bot.start()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot shutdown requested")
