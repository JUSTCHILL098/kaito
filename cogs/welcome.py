import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import traceback

from config import CYAN, WELCOME_FOOTER, AUTO_ROLE_ID, WELCOME_CARD_BG, WELCOME_CARD_ACCENT, WELCOME_CARD_ORIENTATION
from utils import small_caps
from welcome_card import generate_welcome_card

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'welcome_config.json')


def load_config():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_config(config):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, 'w') as f:
        json.dump(config, f, indent=4)


WELCOME_TITLE = small_caps('\U0001f338 welcome to animedex!')


class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_group(name='welcome', aliases=['gw'], invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def welcome(self, ctx):
        """Manage the welcome system. Use subcommands to configure."""
        embed = discord.Embed(
            title=small_caps('welcome system'),
            description=(
                '`!welcome channel #channel` - Set welcome channel\n'
                '`!welcome preview` - Preview welcome message\n'
                '`!welcome disable` - Disable welcome messages\n'
                '`!bye channel #channel` - Set goodbye channel\n'
                '`!bye preview` - Preview goodbye message\n'
                '`!bye disable` - Disable goodbye messages'
            ),
            color=CYAN
        )
        await ctx.send(embed=embed)

    @welcome.command(name='channel')
    @app_commands.describe(channel='The channel to send welcome messages in')
    @commands.has_permissions(administrator=True)
    async def welcome_channel(self, ctx, channel: discord.TextChannel):
        """Set the channel where welcome messages are sent."""
        config = load_config()
        gid = str(ctx.guild.id)
        config.setdefault(gid, {})
        config[gid]['welcome_channel'] = channel.id
        save_config(config)
        embed = discord.Embed(
            description=f'Welcome channel set to {channel.mention}',
            color=CYAN
        )
        await ctx.send(embed=embed)

    @welcome.command(name='preview')
    @commands.has_permissions(administrator=True)
    async def welcome_preview(self, ctx):
        """Preview what the welcome message looks like."""
        await ctx.defer()
        desc = (
            f'Hey {ctx.author.mention}, welcome to Animedex \U0001f338\n\n'
            f"We're happy to have you here!"
        )
        embed = discord.Embed(
            title=WELCOME_TITLE,
            description=desc,
            color=CYAN
        )
        embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
        embed.set_footer(text=WELCOME_FOOTER)

        try:
            image_path = await generate_welcome_card(
                username=ctx.author.display_name,
                member_number=ctx.guild.member_count,
                avatar_url=ctx.author.display_avatar.url,
                quote='[#27d9b5]**Welcome[/] to *Animedex*!\nHope you discover amazing anime here.',
                author='The Staff',
                background=WELCOME_CARD_BG,
                orientation=WELCOME_CARD_ORIENTATION,
                accent=WELCOME_CARD_ACCENT,
                text_color='#FFFFFF',
                muted_color='#8B8B8B',
                quote_color='#FFFFFF',
            )
            embed.set_image(url='attachment://welcome.png')
            await ctx.send(embed=embed, file=discord.File(image_path, filename='welcome.png'))
        except Exception:
            traceback.print_exc()
            await ctx.send(embed=embed)

    @welcome.command(name='disable')
    @commands.has_permissions(administrator=True)
    async def welcome_disable(self, ctx):
        """Disable welcome messages entirely."""
        config = load_config()
        gid = str(ctx.guild.id)
        if gid in config:
            config[gid]['welcome_channel'] = None
            save_config(config)
        await ctx.send('Welcome messages disabled.')

    @commands.hybrid_group(name='bye', invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def bye(self, ctx):
        """Manage the goodbye system."""
        embed = discord.Embed(
            title=small_caps('goodbye system'),
            description=(
                '`!bye channel #channel` - Set goodbye channel\n'
                '`!bye preview` - Preview goodbye message\n'
                '`!bye disable` - Disable goodbye messages'
            ),
            color=CYAN
        )
        await ctx.send(embed=embed)

    @bye.command(name='channel')
    @app_commands.describe(channel='The channel to send goodbye messages in')
    @commands.has_permissions(administrator=True)
    async def bye_channel(self, ctx, channel: discord.TextChannel):
        """Set the channel where goodbye messages are sent."""
        config = load_config()
        gid = str(ctx.guild.id)
        config.setdefault(gid, {})
        config[gid]['bye_channel'] = channel.id
        save_config(config)
        embed = discord.Embed(
            description=f'Goodbye channel set to {channel.mention}',
            color=CYAN
        )
        await ctx.send(embed=embed)

    @bye.command(name='preview')
    @commands.has_permissions(administrator=True)
    async def bye_preview(self, ctx):
        """Preview what the goodbye message looks like."""
        embed = discord.Embed(
            title=small_caps('goodbye'),
            description=f'{ctx.author.display_name} has left the server. We will miss you!',
            color=CYAN
        )
        embed.set_footer(text=WELCOME_FOOTER)
        await ctx.send(embed=embed)

    @bye.command(name='disable')
    @commands.has_permissions(administrator=True)
    async def bye_disable(self, ctx):
        """Disable goodbye messages entirely."""
        config = load_config()
        gid = str(ctx.guild.id)
        if gid in config:
            config[gid]['bye_channel'] = None
            save_config(config)
        await ctx.send('Goodbye messages disabled.')

    @commands.Cog.listener()
    async def on_member_join(self, member):
        auto_role = member.guild.get_role(AUTO_ROLE_ID)
        if auto_role:
            try:
                await member.add_roles(auto_role, reason='Auto role on join')
            except:
                pass

        config = load_config()
        gid = str(member.guild.id)
        data = config.get(gid, {})
        channel_id = data.get('welcome_channel')
        if not channel_id:
            return
        channel = member.guild.get_channel(channel_id)
        if not channel:
            return

        embed = discord.Embed(
            title=WELCOME_TITLE,
            description=(
                f'Hey {member.mention}, welcome to Animedex \U0001f338\n\n'
                f"We're happy to have you here!"
            ),
            color=CYAN
        )
        embed.set_thumbnail(url=member.guild.icon.url if member.guild.icon else None)
        embed.set_footer(text=WELCOME_FOOTER)

        try:
            image_path = await generate_welcome_card(
                username=member.display_name,
                member_number=member.guild.member_count,
                avatar_url=member.display_avatar.url,
                quote='[#27d9b5]**Welcome[/] to *Animedex*!\nHope you discover amazing anime here.',
                author='The Staff',
                background=WELCOME_CARD_BG,
                orientation=WELCOME_CARD_ORIENTATION,
                accent=WELCOME_CARD_ACCENT,
                text_color='#FFFFFF',
                muted_color='#8B8B8B',
                quote_color='#FFFFFF',
            )
            embed.set_image(url='attachment://welcome.png')
            await channel.send(embed=embed, file=discord.File(image_path, filename='welcome.png'))
        except Exception:
            traceback.print_exc()
            await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        config = load_config()
        gid = str(member.guild.id)
        data = config.get(gid, {})
        channel_id = data.get('bye_channel')
        if not channel_id:
            return
        channel = member.guild.get_channel(channel_id)
        if not channel:
            return
        embed = discord.Embed(
            title=small_caps('goodbye'),
            description=f'{member.display_name} has left the server. We will miss you!',
            color=CYAN
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=WELCOME_FOOTER)
        await channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Welcome(bot))
