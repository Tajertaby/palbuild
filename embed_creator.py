import discord

ILOVEPCS_BLUE: int = 9806321


def _create_embed(title=None, description=None) -> discord.Embed:
    """
    Create a standardized embed with consistent styling.

    Args:
        description: The text content for the embed

    Returns:
        A formatted discord.Embed object
    """
    return discord.Embed(title=title, description=description, color=ILOVEPCS_BLUE)
