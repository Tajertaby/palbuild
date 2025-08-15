import discord

ILOVEPCS_BLUE: int = 9806321


def create_embed(title=None, description=None, title_url=None, image_url=None, footer_text=None, footer_url=None, thumbnail_url=None) -> discord.Embed:
    """
    Create a standardized embed with consistent styling.

    Args:
        description: The text content for the embed

    Returns:
        A formatted discord.Embed object
    """
    embed = discord.Embed(title=title, description=description, url=title_url, color=ILOVEPCS_BLUE)
    if image_url:
        embed.set_image(url=image_url)
    if footer_text:
        embed.set_footer(text=footer_text, icon_url=footer_url)
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    return embed