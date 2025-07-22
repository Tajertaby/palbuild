**Palbuild Installation**

1. Install Git and Python
2. Run `git clone https://github.com/Tajertaby/palbuild.git`. It will create a new folder called `palbuild-main`.
3. Copy the path to `palbuild-main`. Then run `cd COPIED PATH`
4. Run `pip install -r requirements.txt`
5. Follow this [site](https://www.writebots.com/discord-bot-token/) on instructions on how to create a new Discord bot.
6. In `secrets.env`, replace `YOUR_TOKEN_HERE` with your actual bot token.
7. Run the `main.py` file in order to start the bot.
- Host Locally?
On Windows, use PowerShell and run `python PATH_TO_FILE`
On MacOS/Linux, use terminal and run `python3 PATH_TO_FILE`
- VPS Hosting?
Use screen to ensure persistence, even when you're not connected to a VPS. Here is a link to a [screen tutorial](https://contabo.com/blog/what-is-screen-and-how-to-use-it-on-a-vps/).

**Bot owner specific Discord commands:**

`!load COG_NAME1 COG_NAME2 COG_NAME3` Load cog(s).

`!unload COG_NAME1 COG_NAME2 COG_NAME3` Unload cog(s).

`!reload COG_NAME1 COG_NAME2 COG_NAME3` Reload cog(s).


- Replace `COG_NAME` with the name of your cog file, **DO NOT** include the `.py` file extention. You can load/unload/reload as many cogs as you want.

`!stop` Shut down the bot.

`!restart` Restart the bot.

**Contact**

Join this [Discord server](https://discord.gg/UEbE5PZUSq) for bot related issues.
