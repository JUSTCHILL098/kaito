import discord
from discord.ext import commands
from discord import app_commands

from config import CYAN, ANNOUNCEMENT_FOOTER
from utils import small_caps


class Announcements(commands.Cog):
    """Announcement and delete commands."""

    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name='announcement')
    @app_commands.describe(
        channel='Channel to send the announcement in',
        title='Announcement title',
        message='Announcement message body'
    )
    @commands.has_permissions(manage_messages=True)
    async def announcement(self, ctx, channel: discord.TextChannel, title: str, *, message: str):
        """Send a styled announcement embed to a channel."""
        embed = discord.Embed(
            title=title,
            description=message,
            color=CYAN
        )
        embed.set_author(
            name='Announcements',
            icon_url=ctx.guild.icon.url if ctx.guild.icon else None
        )
        embed.set_footer(text=ANNOUNCEMENT_FOOTER)
        embed.timestamp = discord.utils.utcnow()

        await channel.send(embed=embed)

        embed_done = discord.Embed(
            description=f'{small_caps("announcement sent")} to {channel.mention}',
            color=CYAN
        )
        await ctx.send(embed=embed_done, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Announcements(bot))
