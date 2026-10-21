import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import Button, View
import time
import os
import traceback

from config import CYAN, WELCOME_FOOTER, RULES_CHANNEL_ID, BOT_OWNER_NAME, BANNER_URL
from utils import small_caps


class _QuoteColorButton(Button):
    def __init__(self, color, style):
        super().__init__(label=color.title(), style=style, custom_id=f'qcol_{color}')
        self.color = color

    async def callback(self, interaction):
        await self.view.apply_color(interaction, self.color)


class _QuoteView(View):
    def __init__(self, gen):
        super().__init__(timeout=600)
        self.gen = dict(gen)
        self.gen['color'] = 'gold'
        for c, st in (('gold', discord.ButtonStyle.success),
                      ('silver', discord.ButtonStyle.secondary),
                      ('blue', discord.ButtonStyle.primary)):
            self.add_item(_QuoteColorButton(c, st))

    async def apply_color(self, interaction, color):
        try:
            await interaction.response.defer()
            gen = dict(self.gen)
            gen['color'] = color
            from welcome_card import generate_quote_card
            path = await generate_quote_card(**gen)
            try:
                await interaction.message.edit(
                    attachments=[discord.File(path, 'quote.png')],
                    view=self
                )
            except Exception:
                await interaction.edit_original_response(
                    attachments=[discord.File(path, 'quote.png')],
                    view=self
                )
        except Exception:
            traceback.print_exc()
            try:
                await interaction.followup.send('Could not re-render the quote.', ephemeral=True)
            except Exception:
                pass


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = time.time()

    def _banner_file(self):
        path = os.path.abspath(os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'assets', 'banner.gif'
        ))
        if os.path.exists(path):
            return discord.File(path, filename='banner.gif')
        return None

    # ─── /alive ──────────────────────────────────────────────
    @commands.hybrid_command(name='alive')
    async def alive(self, ctx):
        """Check if the bot is alive."""
        await ctx.defer()
        uptime_seconds = int(time.time() - self.start_time)
        days = uptime_seconds // 86400
        hours = (uptime_seconds % 86400) // 3600
        minutes = (uptime_seconds % 3600) // 60
        seconds = uptime_seconds % 60
        uptime_str = f'{days}d {hours}h {minutes}m {seconds}s'

        intro = small_caps("i'm " + self.bot.user.name)
        description = (
            f'\u26a1  {small_caps(f"yoo {ctx.author.display_name}")}\n'
            f'{intro}\n'
            f'──────────────────\n'
            f'{small_caps("creator")} \u232f `{BOT_OWNER_NAME}`\n'
            f'{small_caps("uptime")} \u232f `{uptime_str}`\n'
            f'{small_caps("servers")} \u232f `{len(self.bot.guilds)}`\n'
            f'{small_caps("commands")} \u232f `{len(self.bot.commands)}`\n'
            f'{small_caps("version")} \u232f `discord.py {discord.__version__}`'
        )

        embed = discord.Embed(
            description=description,
            color=CYAN
        )
        await ctx.send(embed=embed)

    # ─── /ping ───────────────────────────────────────────────
    @commands.hybrid_command(name='ping')
    async def ping(self, ctx):
        """Check the bot's latency."""
        latency = round(self.bot.latency * 1000)
        embed = discord.Embed(
            title=small_caps('pong!'),
            description=f'Latency: `{latency}ms`',
            color=CYAN
        )
        await ctx.send(embed=embed)

    # ─── /rules ──────────────────────────────────────────────
    @commands.hybrid_command(name='rules')
    @app_commands.describe(channel='Channel to send rules to')
    @commands.has_permissions(administrator=True)
    async def rules(self, ctx, channel: discord.TextChannel = None):
        """Post the server rules with a styled embed."""
        channel = channel or ctx.guild.get_channel(RULES_CHANNEL_ID) or ctx.channel

        embed = discord.Embed(
            title=small_caps('server rules'),
            description=(
                f'\u2757 Breaking any rule may result in a `warn`, `mute`, '
                f'`kick`, or `ban` depending on severity.'
            ),
            color=CYAN
        )
        embed.set_author(
            name=ctx.guild.name,
            icon_url=ctx.guild.icon.url if ctx.guild.icon else None
        )

        rules = [
            ('be respectful', 'Treat everyone with respect. Harassment, hate speech, and toxic behavior are not tolerated.'),
            ('no spam', 'No spam messages, spam emojis, or repeated mentions. Keep chats clean.'),
            ('follow discord tos', 'You must be 13+ and follow Discord\u2019s Terms of Service and Community Guidelines.'),
            ('no nsfw content', 'Posting NSFW or inappropriate content is strictly prohibited.'),
            ('use appropriate channels', 'Keep topics in their correct channels; off-topic posts may be moved or deleted.'),
            ('no advertising', 'Do not advertise other servers, products, or services without staff permission.'),
            ('follow staff instructions', 'Staff have the final say. If you disagree, open a `ticket` to appeal.'),
        ]
        for i, (name, text) in enumerate(rules, 1):
            embed.add_field(
                name=f'{i}. {small_caps(name)}',
                value=text,
                inline=False
            )

        embed.add_field(
            name='\u26a0\ufe0f note',
            value='Punishments are decided by staff based on severity and history.',
            inline=False
        )
        embed.set_footer(text=WELCOME_FOOTER)
        embed.set_image(url=BANNER_URL)
        await channel.send(embed=embed)

        if channel.id != ctx.channel.id:
            embed_done = discord.Embed(
                description=f'Rules sent to {channel.mention}',
                color=CYAN
            )
            await ctx.send(embed=embed_done, ephemeral=True)
        else:
            try:
                await ctx.message.delete()
            except:
                pass

    # ─── /quote ──────────────────────────────────────────────
    @commands.hybrid_command(name='quote', aliases=['quotes'])
    @app_commands.describe(text='Turn a message into a quote image.')
    async def quote(self, ctx, text: str):
        """Turn a message into a quote image."""
        await ctx.defer()
        try:
            from welcome_card import generate_quote_card
            gen = dict(
                text=text,
                author=ctx.author.display_name,
                username=ctx.author.name,
                nickname=ctx.author.display_name,
                avatar_url=ctx.author.display_avatar.url,
                background=None,
                orientation='landscape',
                accent='#cf9a0d',
                text_color='#F5F5F5',
                muted_color='#9A9A9A',
                quote_color='#FFFFFF',
                font_name='DelaGothicOne-Regular.ttf',
                color='gold',
            )
            path = await generate_quote_card(**gen)
            await ctx.send(file=discord.File(path, 'quote.png'), view=_QuoteView(gen))
        except Exception:
            traceback.print_exc()
            embed = discord.Embed(
                title=small_caps('\u201c quote \u201d'),
                description=f'\u201c{text}\u201d',
                color=CYAN
            )
            embed.set_footer(text=f'\u2014 {ctx.author.display_name}')
            await ctx.send(embed=embed)

    # ─── /help ───────────────────────────────────────────────
    @commands.hybrid_command(name='help')
    async def help(self, ctx):
        """Show all available commands."""
        embed = discord.Embed(
            title=small_caps('bot commands'),
            description='Prefix: `!` or `/`',
            color=CYAN
        )
        embed.add_field(
            name=small_caps('moderation'),
            value=(
                '`kick` - Kick a member\n'
                '`ban` - Ban a member\n'
                '`unban` - Unban a user by ID\n'
                '`mute` - Timeout a member\n'
                '`unmute` - Remove timeout\n'
                '`warn` - Warn a member\n'
                '`purge` - Bulk delete messages\n'
                '`lock` - Lock a channel\n'
                '`unlock` - Unlock a channel\n'
                '`slowmode` - Set channel slowmode'
            ),
            inline=False
        )
        embed.add_field(
            name=small_caps('tickets'),
            value=(
                '`/ticket panel` - Send ticket panel\n'
                '`/ticket-role add/remove @role` - Manage support roles\n'
                '`/ticket-claim` - Claim a ticket'
            ),
            inline=False
        )
        embed.add_field(
            name=small_caps('welcome / goodbye'),
            value=(
                '`welcome channel #ch` - Set welcome channel\n'
                '`welcome preview` - Preview welcome\n'
                '`welcome disable` - Disable welcome\n'
                '`bye channel #ch` - Set goodbye channel\n'
                '`bye preview` - Preview goodbye\n'
                '`bye disable` - Disable goodbye'
            ),
            inline=False
        )
        embed.add_field(
            name=small_caps('leveling'),
            value='`rank [user]`, `leaderboard [page]`',
            inline=False
        )
        embed.add_field(
            name=small_caps('utility'),
            value=(
                '`alive` - Check bot status\n'
                '`ping` - Check bot latency\n'
                '`rules` - Post server rules\n'
                '`quote` - Send a styled quote' + '  *(alias: `quotes`)*'
            ),
            inline=False
        )
        embed.add_field(
            name=small_caps('music'),
            value=(
                '`play <song>` - Play from URL or search\n'
                '`playlist <query>` - Play a YouTube playlist\n'
                '`search <query>` - Search and pick tracks\n'
                '`queue` - Show the queue\n'
                '`skip` / `skipto #` - Skip tracks\n'
                '`remove 2,3` / `move 2 5` - Manage the queue\n'
                '`shuffle` / `loop` - Queue controls\n'
                '`volume [0-100]` - Show or set volume\n'
                '`pause` / `resume` / `stop` - Playback control\n'
                '`nowplaying` - Current track\n'
                '`lyrics [title]` - Fetch lyrics'
            ),
            inline=False
        )
        embed.add_field(
            name=small_caps('other'),
            value=(
                '`/announcement` - Send announcement embed\n'
                '`/delete` - Delete a message by ID'
            ),
            inline=False
        )
        embed.set_footer(text=WELCOME_FOOTER)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Utility(bot))
