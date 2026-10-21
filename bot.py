import discord
from discord.ext import commands
import os
import asyncio
import traceback
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')


def build_bot():
    intents = discord.Intents.all()
    bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

    @bot.event
    async def on_ready():
        print(f'Logged in as {bot.user} ({bot.user.id})')
        print(f'Using discord.py v{discord.__version__}')
        await bot.change_presence(activity=discord.Activity(
            type=discord.ActivityType.watching, name='over Animedex'))
        try:
            synced = await bot.tree.sync()
            print(f'Synced {len(synced)} slash command(s)')
        except Exception as e:
            print(f'Failed to sync slash commands: {e}')

        for guild in bot.guilds:
            print(f'  - {guild.name} ({guild.id})')

    @bot.event
    async def on_command_error(ctx, error):
        traceback.print_exc()
        try:
            await ctx.send(f'Error: {error}')
        except Exception:
            pass

    @bot.event
    async def on_app_command_error(interaction, error):
        traceback.print_exc()
        try:
            if interaction.response.is_done():
                await interaction.followup.send(f'Error: {error}', ephemeral=True)
            else:
                await interaction.response.send_message(f'Error: {error}', ephemeral=True)
        except Exception:
            pass

    return bot


async def load_cogs(bot):
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py') and filename != '__init__.py':
            await bot.load_extension(f'cogs.{filename[:-3]}')
            print(f'Loaded cog: {filename[:-3]}')


async def main():
    while True:
        bot = build_bot()
        try:
            async with bot:
                await load_cogs(bot)
                await bot.start(TOKEN)
            print('Bot stopped cleanly.')
            break
        except discord.LoginFailure as e:
            print(f'Login failed - check DISCORD_TOKEN in .env: {e}')
            break
        except Exception as e:
            print(f'Connection error ({type(e).__name__}): {e}')
            print('Retrying in 10 seconds...')
            await asyncio.sleep(10)


asyncio.run(main())