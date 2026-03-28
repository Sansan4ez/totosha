#!/usr/bin/env python3
"""
LocalTopSH Telegram Bot (Python/aiogram)
Entry point - orchestrates all modules
"""

import asyncio
import logging
from aiogram import types
from aiohttp import web

from config import TELEGRAM_TOKEN, CORE_URL, BOT_PORT, CONFIG
from observability import setup_observability
import state
from state import bot, dp
from server import create_http_app
from thoughts import start_thoughts_task

# Import handlers to register them with dispatcher
import handlers  # noqa: F401

setup_observability("bot")
logger = logging.getLogger("bot")


async def main():
    if not TELEGRAM_TOKEN:
        logger.error("Missing TELEGRAM_TOKEN")
        return
    
    # Get bot info
    me = await bot.get_me()
    state.bot_username = me.username or ""
    state.bot_id = me.id
    
    logger.info("LocalTopSH Bot (Python)")
    logger.info("Bot: @%s (%s)", state.bot_username, state.bot_id)
    logger.info("Core: %s", CORE_URL)
    logger.info("HTTP: http://0.0.0.0:%s", BOT_PORT)
    logger.info("Max concurrent: %s", CONFIG.max_concurrent)
    
    # Set commands
    await bot.set_my_commands([
        types.BotCommand(command="start", description="Start / Help"),
        types.BotCommand(command="clear", description="Clear session"),
        types.BotCommand(command="status", description="Show status"),
    ])
    
    # Start HTTP server
    http_app = create_http_app()
    runner = web.AppRunner(http_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", BOT_PORT)
    await site.start()
    logger.info("HTTP server on http://0.0.0.0:%s", BOT_PORT)
    
    # Start autonomous thoughts
    thoughts_task = start_thoughts_task()
    logger.info("Thoughts task started")
    
    # Start polling
    logger.info("Started, connecting to core at %s", CORE_URL)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
