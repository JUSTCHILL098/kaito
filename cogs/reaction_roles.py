import discord
from discord.ext import commands
from discord import app_commands
import json
import os

from config import WELCOME_COLOR

DATA_FILE = 'data/reaction_roles.json'

def load_config():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_config(config):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, 'w') as f:
        json.dump(config, f, indent=4)

class ReactionRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_group(name='reactrole', aliases=['rr'], invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def reactrole(self, ctx):
        embed = discord.Embed(
            title='Reaction Role Commands',
            description=(
                '`!reactrole add <message_id> @role :emoji:` - Add reaction role\n'
                '`!reactrole remove <message_id> @role` - Remove a reaction role\n'
                '`!reactrole list` - List all reaction roles\n'
                '`!reactrole panel #channel` - Create reaction role panel'
            ),
            color=WELCOME_COLOR
        )
        await ctx.send(embed=embed)

    @reactrole.command(name='add')
    @app_commands.describe(message_id='ID of the message', role='Role to assign', emoji='Emoji to react with')
    @commands.has_permissions(administrator=True)
    async def rr_add(self, ctx, message_id: str, role: discord.Role, emoji: str):
        try:
            mid = int(message_id)
            msg = await ctx.channel.fetch_message(mid)
        except:
            await ctx.send('Message not found in this channel.', ephemeral=True)
            return

        try:
            await msg.add_reaction(emoji)
        except discord.HTTPException:
            await ctx.send('Invalid emoji.', ephemeral=True)
            return

        config = load_config()
        gid = str(ctx.guild.id)
        config.setdefault(gid, {})
        key = str(mid)
        config[gid].setdefault(key, {})

        if emoji in config[gid][key]:
            await ctx.send('This emoji is already assigned on this message.', ephemeral=True)
            return

        config[gid][key][emoji] = role.id
        save_config(config)
        await ctx.send(f'Reaction role added: {emoji} -> {role.mention}')

    @reactrole.command(name='remove')
    @app_commands.describe(message_id='ID of the message', role='Role to remove')
    @commands.has_permissions(administrator=True)
    async def rr_remove(self, ctx, message_id: str, role: discord.Role):
        config = load_config()
        gid = str(ctx.guild.id)
        key = str(message_id)
        data = config.get(gid, {}).get(key, {})

        to_delete = None
        for emoji, rid in data.items():
            if rid == role.id:
                to_delete = emoji
                break

        if not to_delete:
            await ctx.send('No reaction role found for that role on that message.', ephemeral=True)
            return

        del config[gid][key][to_delete]
        if not config[gid][key]:
            del config[gid][key]
        save_config(config)
        await ctx.send(f'Reaction role removed for {role.mention}')

    @reactrole.command(name='list')
    @commands.has_permissions(administrator=True)
    async def rr_list(self, ctx):
        config = load_config()
        gid = str(ctx.guild.id)
        data = config.get(gid, {})
        if not data:
            await ctx.send('No reaction roles configured.', ephemeral=True)
            return

        embed = discord.Embed(title='Reaction Roles', color=WELCOME_COLOR)
        for msg_id, reactions in data.items():
            lines = []
            for emoji, rid in reactions.items():
                role = ctx.guild.get_role(rid)
                if role:
                    lines.append(f'{emoji} -> {role.mention}')
            if lines:
                embed.add_field(name=f'Message: {msg_id}', value='\n'.join(lines), inline=False)
        await ctx.send(embed=embed)

    @reactrole.command(name='panel')
    @app_commands.describe(channel='Channel to send the panel in (default: current)')
    @commands.has_permissions(administrator=True)
    async def rr_panel(self, ctx, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        embed = discord.Embed(
            title='Reaction Roles',
            description='React to get the corresponding roles!',
            color=WELCOME_COLOR
        )
        await channel.send(embed=embed)
        if channel.id != ctx.channel.id:
            await ctx.send(f'Panel sent to {channel.mention}')

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.user_id == self.bot.user.id:
            return
        if not payload.guild_id:
            return

        config = load_config()
        gid = str(payload.guild_id)
        key = str(payload.message_id)
        data = config.get(gid, {}).get(key, {})
        if not data:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        emoji_str = str(payload.emoji)
        if emoji_str not in data:
            return

        role_id = data[emoji_str]
        role = guild.get_role(role_id)
        if not role:
            return

        member = guild.get_member(payload.user_id)
        if not member:
            return

        await member.add_roles(role, reason='Reaction role')
        try:
            channel = guild.get_channel(payload.channel_id)
            if channel:
                msg = await channel.fetch_message(payload.message_id)
                await msg.remove_reaction(payload.emoji, member)
        except:
            pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        if payload.user_id == self.bot.user.id:
            return
        if not payload.guild_id:
            return

        config = load_config()
        gid = str(payload.guild_id)
        key = str(payload.message_id)
        data = config.get(gid, {}).get(key, {})
        if not data:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        emoji_str = str(payload.emoji)
        if emoji_str not in data:
            return

        role_id = data[emoji_str]
        role = guild.get_role(role_id)
        if not role:
            return

        member = guild.get_member(payload.user_id)
        if not member:
            return

        await member.remove_roles(role, reason='Reaction role removed')

async def setup(bot):
    await bot.add_cog(ReactionRoles(bot))
