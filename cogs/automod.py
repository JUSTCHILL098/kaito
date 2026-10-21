import discord
from discord.ext import commands
import re
import json
import os
import datetime

from config import CYAN, AUTOMOD_LOG_CHANNEL_ID, AUTOMOD_TIMEOUT_MINUTES, AUTOMOD_MAX_WARNINGS
from utils import small_caps

WORDS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'banned_words.json')


def _load_banned_words():
    if os.path.exists(WORDS_FILE):
        with open(WORDS_FILE, 'r') as f:
            data = json.load(f)
            return data.get('banned_words', [])
    return []


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s]', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def _contains_banned(text: str) -> bool:
    """Whole-word profanity check.

    Substring matching is intentionally avoided: it flagged innocent words
    such as ``hello`` (contains ``hell``), ``class`` (contains ``ass``) and
    any sentence containing the standalone letter ``i`` or ``a``.
    """
    banned = _load_banned_words()
    normalized = _normalize(text)
    if not normalized:
        return False

    tokens = set(normalized.split())
    for entry in banned:
        nb = _normalize(entry)
        if not nb:
            continue
        if ' ' in nb:
            # Explicitly spaced-out evasion patterns, e.g. "f u c k".
            if nb in normalized:
                return True
        elif nb in tokens:
            return True
    return False


class Automod(commands.Cog):
    """Automatic moderation for abusive language."""

    def __init__(self, bot):
        self.bot = bot
        self.warnings = {}

    def _add_warning(self, guild_id: int, user_id: int) -> int:
        gid, uid = str(guild_id), str(user_id)
        self.warnings.setdefault(gid, {})
        self.warnings[gid][uid] = self.warnings[gid].get(uid, 0) + 1
        return self.warnings[gid][uid]

    def _reset_warnings(self, guild_id: int, user_id: int):
        self.warnings.get(str(guild_id), {}).pop(str(user_id), None)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if message.author.guild_permissions.manage_messages:
            return
        if not _contains_banned(message.content):
            return

        guild = message.guild
        user = message.author
        count = self._add_warning(guild.id, user.id)

        try:
            await message.delete()
        except:
            pass

        log_channel = guild.get_channel(AUTOMOD_LOG_CHANNEL_ID) if AUTOMOD_LOG_CHANNEL_ID else None

        if count < AUTOMOD_MAX_WARNINGS:
            # Ephemeral DM warning to the user
            warn_embed = discord.Embed(
                title=small_caps('language warning'),
                description=(
                    f'Please watch your language in **{guild.name}**.\n\n'
                    f'**Warning {count}/{AUTOMOD_MAX_WARNINGS}**\n'
                    f'Channel: {message.channel.mention}'
                ),
                color=CYAN
            )
            try:
                await user.send(embed=warn_embed)
            except discord.Forbidden:
                pass

            if log_channel:
                log_embed = discord.Embed(
                    title=small_caps('automod warning'),
                    description=(
                        f'{user.mention} ({user.id}) received warning **{count}/{AUTOMOD_MAX_WARNINGS}**\n'
                        f'Channel: {message.channel.mention}\n'
                        f'Message: `{message.content[:200]}`'
                    ),
                    color=CYAN
                )
                await log_channel.send(embed=log_embed)

        else:
            until = discord.utils.utcnow() + datetime.timedelta(minutes=AUTOMOD_TIMEOUT_MINUTES)
            try:
                await user.timeout(until, reason=f'Automod: {AUTOMOD_MAX_WARNINGS} abusive language warnings')
            except:
                pass

            self._reset_warnings(guild.id, user.id)

            timeout_embed = discord.Embed(
                title=small_caps('timed out'),
                description=(
                    f'You have been timed out in **{guild.name}** for **{AUTOMOD_TIMEOUT_MINUTES} minutes**.\n\n'
                    f'Reason: Exceeded {AUTOMOD_MAX_WARNINGS} language warnings.'
                ),
                color=CYAN
            )
            try:
                await user.send(embed=timeout_embed)
            except discord.Forbidden:
                pass

            if log_channel:
                log_embed = discord.Embed(
                    title=small_caps('automod timeout'),
                    description=(
                        f'{user.mention} ({user.id}) was timed out for **{AUTOMOD_TIMEOUT_MINUTES}m**\n'
                        f'Channel: {message.channel.mention}\n'
                        f'Message: `{message.content[:200]}`'
                    ),
                    color=CYAN
                )
                await log_channel.send(embed=log_embed)


async def setup(bot):
    await bot.add_cog(Automod(bot))
