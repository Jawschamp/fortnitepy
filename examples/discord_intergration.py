import os, json, fortnitepy
from discord.ext import commands
import logging
import sys


logger = logging.getLogger('fortnitepy')
logger = logging.getLogger('discord')
logger.setLevel(level=logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)


discord_bot = commands.Bot(
    command_prefix='!',
    description='My discord + fortnite bot!',
    case_insensitive=True
)


email = "your@email"
password = "password Here"
filename = 'device_auths.json'


def get_device_auth_details():
    if os.path.isfile(filename):
        with open(filename, 'r') as fp:
            return json.load(fp)
    return {}


def store_device_auth_details(email, details):
    existing = get_device_auth_details()
    existing[email] = details


    with open(filename, 'w') as fp:
        json.dump(existing, fp)


device_auth_details = get_device_auth_details().get(email, {})
fortnite_client = fortnitepy.Client(
    auth=fortnitepy.AdvancedAuth(
        email=email,
        password=password,
        prompt_exchange_code=True,
        delete_existing_device_auths=True,
        **device_auth_details
    )
)


@discord_bot.event
async def on_ready():
    print('Discord bot ready')
    await fortnite_client.start()


@fortnite_client.event
async def event_ready():
    print('Fortnite client ready')


@discord_bot.event
async def on_message(message):
    print('Received message from {0.author.display_name} | Content "{0.content}"'.format(message))


@fortnite_client.event
async def event_friend_message(message):
    print('Received message from {0.author.display_name} | Content "{0.content}"'.format(message))


# discord command
@commands.command()
async def mycommand(ctx):
    await ctx.send('Hello there!')


discord_bot.run('Token Here')
