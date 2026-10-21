import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import math
import random
import datetime

from config import WELCOME_COLOR

DATA_FILE = 'data/leveling.json'

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_data(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

XP_PER_MSG = (10, 20)
XP_COOLDOWN = 60
BASE_XP = 100
XP_GROWTH = 1.5

def xp_for_level(level):
    return int(BASE_XP * (level ** XP_GROWTH))

def level_from_xp(total_xp):
    return int((total_xp / BASE_XP) ** (1 / XP_GROWTH))

class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cooldowns = {}

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        now = datetime.datetime.now().timestamp()
        user_id = str(message.author.id)
        guild_id = str(message.guild.id)

        if user_id in self.cooldowns:
            if now - self.cooldowns[user_id] < XP_COOLDOWN:
                return

        self.cooldowns[user_id] = now
        xp_gain = random.randint(*XP_PER_MSG)

        data = load_data()
        data.setdefault(guild_id, {})
        data[guild_id].setdefault(user_id, {'xp': 0, 'level': 0})

        user_data = data[guild_id][user_id]
        old_level = user_data['level']
        user_data['xp'] += xp_gain
        user_data['level'] = level_from_xp(user_data['xp'])
        user_data['name'] = message.author.display_name
        save_data(data)

        if user_data['level'] > old_level:
            channel = message.channel
            embed = discord.Embed(
                title='\U0001f31f Level Up!',
                description=f'{message.author.mention} reached **level {user_data["level"]}**!',
                color=discord.Color.gold()
            )
            embed.set_thumbnail(url=message.author.display_avatar.url)
            await channel.send(embed=embed)

    @commands.hybrid_command(name='rank')
    @app_commands.describe(member='The member to check rank for')
    async def rank(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        data = load_data()
        gid = str(ctx.guild.id)
        uid = str(member.id)

        gdata = data.get(gid, {})
        user_data = gdata.get(uid)
        if not user_data:
            embed = discord.Embed(description=f'{member.mention} has no XP yet.', color=WELCOME_COLOR)
            await ctx.send(embed=embed)
            return

        sorted_users = sorted(gdata.items(), key=lambda x: x[1]['xp'], reverse=True)
        rank = next((i + 1 for i, (uid_, _) in enumerate(sorted_users) if uid_ == uid), len(sorted_users))

        next_level = user_data['level'] + 1
        xp_needed = xp_for_level(next_level)
        xp_current = user_data['xp']
        xp_into_level = xp_current - xp_for_level(user_data['level'])
        xp_for_next = xp_needed - xp_for_level(user_data['level'])

        progress = min(xp_into_level / xp_for_next * 100, 100) if xp_for_next > 0 else 0
        bar_length = 10
        filled = int(progress / 100 * bar_length)
        bar = '\u2588' * filled + '\u2591' * (bar_length - filled)

        embed = discord.Embed(
            title=f'{member.display_name}\'s Rank',
            color=WELCOME_COLOR
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name='Level', value=user_data['level'], inline=True)
        embed.add_field(name='XP', value=f'{xp_current:,}', inline=True)
        embed.add_field(name='Rank', value=f'#{rank}', inline=True)
        embed.add_field(name='Progress', value=f'`{bar}` {xp_into_level:,}/{xp_for_next:,} XP', inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='leaderboard', aliases=['lb', 'ranking'])
    @app_commands.describe(page='Page number')
    async def leaderboard(self, ctx, page: int = 1):
        data = load_data()
        gid = str(ctx.guild.id)
        gdata = data.get(gid, {})

        if not gdata:
            embed = discord.Embed(description='No ranking data yet.', color=WELCOME_COLOR)
            await ctx.send(embed=embed)
            return

        sorted_users = sorted(gdata.items(), key=lambda x: x[1]['xp'], reverse=True)

        per_page = 10
        total_pages = max(1, (len(sorted_users) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        start = (page - 1) * per_page
        end = start + per_page
        page_users = sorted_users[start:end]

        medal_emojis = ['\U0001f947', '\U0001f948', '\U0001f949']
        lines = []
        for i, (uid, udata) in enumerate(page_users):
            rank_global = start + i + 1
            medal = medal_emojis[i] if i < 3 else f'`#{rank_global}`'
            member = ctx.guild.get_member(int(uid))
            name = member.mention if member else udata.get('name', f'Unknown ({uid})')
            lines.append(f'{medal} **Lvl {udata["level"]}** {name} \u2014 {udata["xp"]:,} XP')

        embed = discord.Embed(
            title='\U0001f3c6 Leaderboard',
            description='\n'.join(lines),
            color=WELCOME_COLOR
        )
        embed.set_footer(text=f'Page {page}/{total_pages} \u2022 Total {len(sorted_users)} members')
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Leveling(bot))
