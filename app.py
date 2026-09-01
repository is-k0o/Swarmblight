from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from uuid import UUID

import discord
from discord.ext import commands

from budget import BudgetExceeded
from config import Settings, get_settings
from llm import LLMClient, LLMError
from memory import MemoryStore, SQLiteMemoryStore
from policy import PolicyViolation
from renderer import DiscordRenderer, split_discord_message
from router import SwarmRouter

logger = logging.getLogger(__name__)


@dataclass
class Runtime:
    settings: Settings
    memory: MemoryStore
    router: SwarmRouter
    renderer: DiscordRenderer
    session_id: UUID
    lock: asyncio.Lock


def create_bot(settings: Settings | None = None) -> commands.Bot:
    config = settings or get_settings()
    memory = SQLiteMemoryStore(config.database_path)
    llm = LLMClient(config)
    runtime = Runtime(
        settings=config,
        memory=memory,
        router=SwarmRouter(llm=llm, memory=memory, settings=config),
        renderer=DiscordRenderer(config.skaven_level),
        session_id=memory.get_or_create_active_session(),
        lock=asyncio.Lock(),
    )

    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

    def allowed_channel(ctx: commands.Context[commands.Bot]) -> bool:
        channel_id = runtime.settings.discord_channel_id
        return channel_id is None or ctx.channel.id == channel_id

    @bot.event
    async def on_ready() -> None:
        logger.info("Discord bot connected as %s", bot.user)

    @bot.command(name="swarm")
    async def swarm_command(
        ctx: commands.Context[commands.Bot], *, text: str = ""
    ) -> None:
        if not allowed_channel(ctx):
            return
        if not text.strip():
            await ctx.send("Usage: `!swarm <manually supplied text, HTTP request, or logs>`")
            return
        logger.info(
            "Discord message received channel=%s author_id=%s length=%d",
            ctx.channel.id,
            ctx.author.id,
            len(text),
        )
        async with runtime.lock:
            try:
                async with ctx.typing():
                    result = await runtime.router.run(runtime.session_id, text)
                    rendered = runtime.renderer.render_report(
                        result.final_response,
                        result.specialist_responses,
                        result.finding_candidates,
                    )
                    runtime.memory.save_message(
                        runtime.session_id,
                        "assistant",
                        "horned_rat",
                        rendered,
                        raw_json=result.final_response.model_dump(mode="json"),
                    )
                for chunk in split_discord_message(rendered):
                    await ctx.send(chunk)
            except BudgetExceeded as exc:
                logger.warning("Budget refused LLM call: %s", exc)
                await ctx.send(f"NO-NO MORE WARPSTONE. TREASURY EMPTY.\n{exc}")
            except PolicyViolation as exc:
                logger.warning("System policy rejected agent output: %s", exc)
                await ctx.send(f"SYSTEM POLICY REFUSES THIS ACTION.\n{exc}")
            except LLMError:
                logger.exception("LLM processing error")
                await ctx.send("The swarm failed to parse the omen. Check logs and configuration.")
            except Exception:
                logger.exception("Unexpected swarm command error")
                await ctx.send("The swarm hit an unexpected error. Check the local logs.")

    @bot.command(name="status")
    async def status_command(ctx: commands.Context[commands.Bot]) -> None:
        if not allowed_channel(ctx):
            return
        summary = runtime.memory.get_session_summary(runtime.session_id)
        await ctx.send(runtime.renderer.render_status(summary))

    @bot.command(name="reset")
    async def reset_command(
        ctx: commands.Context[commands.Bot], confirmation: str = ""
    ) -> None:
        if not allowed_channel(ctx):
            return
        if confirmation.lower() != "confirm":
            await ctx.send(
                "This permanently deletes the active session. Run `!reset confirm` to proceed."
            )
            return
        async with runtime.lock:
            runtime.memory.delete_session(runtime.session_id)
            runtime.session_id = runtime.memory.create_session()
        logger.info("Active swarm session reset")
        await ctx.send("Active session deleted. A fresh nest is ready-ready.")

    return bot


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()
    if not settings.discord_token:
        raise RuntimeError("DISCORD_TOKEN must be configured in .env")
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY must be configured in .env")
    if not settings.coordinator_model or not settings.specialist_model:
        raise RuntimeError("COORDINATOR_MODEL and SPECIALIST_MODEL must be configured in .env")
    create_bot(settings).run(settings.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
