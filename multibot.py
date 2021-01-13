import asyncio
import discord
import youtubesearchpython as yts
import youtube_dl as youtube
import validators
import cfg
from os import remove

from discord.ext import commands

def is_url(content):
    if(validators.url(content)):
        return True
    else:
        return False

# Suppress noise about console usage from errors
youtube.utils.bug_reports_message = lambda: ''


ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0' # bind to ipv4 since ipv6 addresses cause issues sometimes
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', 
    'options': '-vn'
    }

ytdl = youtube.YoutubeDL(ytdl_format_options)


class VoiceState:
    def __init__(self, bot : commands.Bot):
        self.bot = bot
        self.current = None
        self.voice = None
        self.play_next_song = asyncio.Event()
        self.songs = asyncio.Queue()
        self.audio_player = self.bot.loop.create_task(self.audio_player_task())
    
    def toggle_next(self):
        self.bot.loop.call_soon_threadsafe(self.play_next_song.set)

    async def audio_player_task(self):
        while True:
            self.play_next_song.clear()
            self.current = await self.songs.get()
            await self.current.play(lambda e: self.toggle_next())
            await self.play_next_song.wait()


class Song:
    def __init__(self, ctx, url, loop, filename = None):
        self.ctx = ctx
        self.url = url
        self.loop = loop
        self.filename = filename
        

    async def play(self, toggle_next):
        async with self.ctx.typing():
            player = await YTDLSource.from_url(self.url, loop=self.loop, stream=True)
            self.ctx.voice_client.play(player, after= toggle_next)

        await self.ctx.send('**Now playing**: {}'.format(player.title))

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5, filename=''):
        super().__init__(source, volume)

        self.data = data
        self.filename = filename
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            # take first item from a playlist
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data, filename=filename)


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_states = {}

    def get_voice_state(self, guild):
        state = self.voice_states.get(guild.id)
        if state is None:
            state = VoiceState(self.bot)
            self.voice_states[guild.id] = state
        return state

    @commands.command()
    async def join(self, ctx, channel: discord.VoiceChannel = None):
        """Joins a voice channel"""
        if channel is None:
            return await ctx.author.voice.channel.connect()

        if ctx.voice_client is not None:
            return await ctx.voice_client.move_to(channel)

        await channel.connect()

    @commands.command()
    async def stream(self, ctx, *, url):
        """Streams from a url (same as yt, but doesn't predownload)"""

        async with ctx.typing():
            player = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True)
            ctx.voice_client.play(player, after=lambda e: print('Player error: %s' % e) if e else None)

        await ctx.send('Now playing: {}'.format(player.title))

    @commands.command()
    async def volume(self, ctx, volume: int):
        """Changes the player's volume"""

        if ctx.voice_client is None:
            return await ctx.send("Not connected to a voice channel.")

        ctx.voice_client.source.volume = volume / 100
        await ctx.send("Changed volume to {}%".format(volume))

    @commands.command()
    async def skip(self, ctx):
        """Stop music"""

        #await ctx.voice_client.disconnect()
        try:
            await ctx.voice_client.stop()
        except:
            pass

    @commands.command()
    async def stop(self, ctx):
        """Stops and disconnects the bot from voice"""

        state = self.get_voice_state(ctx.guild)
        if(state is not None):
            for _ in range(state.songs.qsize()):
                state.songs.get_nowait()
                state.songs.task_done()
            try:
                await ctx.voice_client.stop()
            except:
                pass

    @commands.command()
    async def disco(self, ctx : commands.Context, *, query):
        if(ctx.author == self.bot):
            return
        
        state = self.get_voice_state(ctx.guild)
        link = str()
        if(is_url(query)):
            link = query
        else:
            search_res = yts.VideosSearch(query, limit = 1)
            link = search_res.result()['result'][0]['link']
        #Если бот не в канале
        if(ctx.voice_client is None):
            await self.join(ctx)
        if(ctx.voice_client.is_playing()):
            await ctx.send('Enqueued: {}'.format(link))
        await state.songs.put(Song(ctx, link, self.bot.loop))
        


bot = commands.Bot(command_prefix="$")

@bot.event
async def on_ready():
    print("bot started successfully")



bot.add_cog(Music(bot))

bot.run(cfg.TOKEN)