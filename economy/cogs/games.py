"""
Gambling commands - Phase 3.
------------------------------------------
/coinflip /dice /rps /slots /roulette /blackjack

Anti-abuse measures (per the project spec's requirements):
  - Bet amount validated before any RNG or balance change happens
  - Bet is deducted atomically via balance_service (which already rejects
    negative/zero/huge amounts and insufficient funds)
  - A short per-game cooldown (configurable, default 3-5s) prevents rapid-
    fire spam
  - Blackjack tracks one active game per user in memory and disables its
    buttons once resolved, so double-clicking Hit/Stand or starting a
    second game mid-hand is not possible
"""

import discord
from discord import app_commands
from discord.ext import commands

from economy.services import balance_service as bs
from economy.services import games_service as gs
from economy.exceptions import EconomyError, InvalidAmountError

# user_id -> True while they have an active blackjack hand - prevents
# starting a second game or racing button clicks across two views.
_active_blackjack_games: set[int] = set()


def format_money(amount, symbol: str) -> str:
    return f"{symbol}{amount:,.0f}" if isinstance(amount, float) else f"{symbol}{amount:,}"


async def _check_cooldown_and_bet(interaction: discord.Interaction, game: str, bet: int) -> bool:
    """Returns True if OK to proceed (and sets the cooldown). Sends the
    error message itself and returns False otherwise."""
    config = gs.get_game_config(interaction.guild_id, game)

    if not config.enabled:
        await interaction.response.send_message(f"🚫 `/{game}` is currently disabled on this server.", ephemeral=True)
        return False

    remaining = bs.check_cooldown(interaction.guild_id, interaction.user.id, game)
    if remaining:
        await interaction.response.send_message(
            f"⏳ Slow down - try again in {remaining.seconds}s.", ephemeral=True
        )
        return False

    if bet < config.min_bet or bet > config.max_bet:
        await interaction.response.send_message(
            f"❌ Bet must be between {config.min_bet:,} and {config.max_bet:,}.", ephemeral=True
        )
        return False

    bs.set_cooldown(interaction.guild_id, interaction.user.id, game, config.cooldown_seconds)
    return True


class Games(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------- coinflip ----------

    @app_commands.command(name="coinflip", description="Bet on a coinflip")
    @app_commands.describe(bet="How much to bet", choice="heads or tails")
    @app_commands.choices(choice=[
        app_commands.Choice(name="Heads", value="heads"),
        app_commands.Choice(name="Tails", value="tails"),
    ])
    async def coinflip(self, interaction: discord.Interaction, bet: int, choice: app_commands.Choice[str]):
        if not await _check_cooldown_and_bet(interaction, "coinflip", bet):
            return
        settings = bs.get_guild_settings(interaction.guild_id)

        try:
            bs.remove_cash(interaction.guild_id, interaction.user.id, bet, command="coinflip", txn_type="game_bet")
        except EconomyError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return

        result = gs.play_coinflip(choice.value)
        color = discord.Color.green() if result.won else discord.Color.red()
        embed = discord.Embed(title="🪙 Coinflip", color=color)
        embed.add_field(name="Landed on", value=result.landed.title(), inline=True)

        if result.won:
            payout = round(bet * result.payout_multiplier)
            bs.add_cash(interaction.guild_id, interaction.user.id, payout, command="coinflip", txn_type="game_win")
            embed.add_field(name="Result", value=f"✅ Won **{format_money(payout, settings.currency_symbol)}**", inline=True)
        else:
            embed.add_field(name="Result", value=f"❌ Lost **{format_money(bet, settings.currency_symbol)}**", inline=True)

        await interaction.response.send_message(embed=embed)

    # ---------- dice ----------

    @app_commands.command(name="dice", description="Guess a dice roll (1-6) for a 5.5x payout")
    @app_commands.describe(bet="How much to bet", guess="Your guess, 1-6")
    async def dice(self, interaction: discord.Interaction, bet: int, guess: app_commands.Range[int, 1, 6]):
        if not await _check_cooldown_and_bet(interaction, "dice", bet):
            return
        settings = bs.get_guild_settings(interaction.guild_id)

        try:
            bs.remove_cash(interaction.guild_id, interaction.user.id, bet, command="dice", txn_type="game_bet")
        except EconomyError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return

        result = gs.play_dice(guess)
        color = discord.Color.green() if result.won else discord.Color.red()
        embed = discord.Embed(title="🎲 Dice", color=color)
        embed.add_field(name="Rolled", value=str(result.rolled), inline=True)
        embed.add_field(name="Your guess", value=str(guess), inline=True)

        if result.won:
            payout = round(bet * result.payout_multiplier)
            bs.add_cash(interaction.guild_id, interaction.user.id, payout, command="dice", txn_type="game_win")
            embed.add_field(name="Result", value=f"✅ Won **{format_money(payout, settings.currency_symbol)}**", inline=False)
        else:
            embed.add_field(name="Result", value=f"❌ Lost **{format_money(bet, settings.currency_symbol)}**", inline=False)

        await interaction.response.send_message(embed=embed)

    # ---------- rock paper scissors ----------

    @app_commands.command(name="rps", description="Rock paper scissors against the bot")
    @app_commands.describe(bet="How much to bet", choice="rock, paper, or scissors")
    @app_commands.choices(choice=[
        app_commands.Choice(name="Rock", value="rock"),
        app_commands.Choice(name="Paper", value="paper"),
        app_commands.Choice(name="Scissors", value="scissors"),
    ])
    async def rps(self, interaction: discord.Interaction, bet: int, choice: app_commands.Choice[str]):
        if not await _check_cooldown_and_bet(interaction, "rps", bet):
            return
        settings = bs.get_guild_settings(interaction.guild_id)

        try:
            bs.remove_cash(interaction.guild_id, interaction.user.id, bet, command="rps", txn_type="game_bet")
        except EconomyError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return

        result = gs.play_rps(choice.value)
        emoji = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
        embed = discord.Embed(title="✊ Rock Paper Scissors", color=discord.Color.blurple())
        embed.add_field(name="You", value=f"{emoji[choice.value]} {choice.name}", inline=True)
        embed.add_field(name="Bot", value=f"{emoji[result.bot_choice]} {result.bot_choice.title()}", inline=True)

        if result.outcome == "tie":
            embed.add_field(name="Result", value="🤝 Tie - bet refunded", inline=False)
            bs.add_cash(interaction.guild_id, interaction.user.id, bet, command="rps", txn_type="game_refund")
        elif result.outcome == "win":
            payout = round(bet * result.payout_multiplier)
            bs.add_cash(interaction.guild_id, interaction.user.id, payout, command="rps", txn_type="game_win")
            embed.add_field(name="Result", value=f"✅ Won **{format_money(payout, settings.currency_symbol)}**", inline=False)
            embed.color = discord.Color.green()
        else:
            embed.add_field(name="Result", value=f"❌ Lost **{format_money(bet, settings.currency_symbol)}**", inline=False)
            embed.color = discord.Color.red()

        await interaction.response.send_message(embed=embed)

    # ---------- slots ----------

    @app_commands.command(name="slots", description="Spin the slot machine")
    @app_commands.describe(bet="How much to bet")
    async def slots(self, interaction: discord.Interaction, bet: int):
        if not await _check_cooldown_and_bet(interaction, "slots", bet):
            return
        settings = bs.get_guild_settings(interaction.guild_id)

        try:
            bs.remove_cash(interaction.guild_id, interaction.user.id, bet, command="slots", txn_type="game_bet")
        except EconomyError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return

        result = gs.play_slots()
        reels_display = " | ".join(result.reels)
        embed = discord.Embed(title="🎰 Slots", description=f"## {reels_display}", color=discord.Color.gold() if result.won else discord.Color.red())

        if result.won:
            payout = round(bet * result.payout_multiplier)
            bs.add_cash(interaction.guild_id, interaction.user.id, payout, command="slots", txn_type="game_win")
            label = "JACKPOT!" if not result.two_match else "Small win"
            embed.add_field(name=label, value=f"✅ Won **{format_money(payout, settings.currency_symbol)}**")
        else:
            embed.add_field(name="No match", value=f"❌ Lost **{format_money(bet, settings.currency_symbol)}**")

        await interaction.response.send_message(embed=embed)

    # ---------- roulette ----------

    @app_commands.command(name="roulette", description="Bet on red, black, green, or a specific number (0-36)")
    @app_commands.describe(bet="How much to bet", choice="red, black, green, or a number 0-36")
    async def roulette(self, interaction: discord.Interaction, bet: int, choice: str):
        choice = choice.strip().lower()
        if choice not in ("red", "black", "green"):
            if not choice.isdigit() or not (0 <= int(choice) <= 36):
                await interaction.response.send_message("❌ Choice must be red, black, green, or a number 0-36.", ephemeral=True)
                return

        if not await _check_cooldown_and_bet(interaction, "roulette", bet):
            return
        settings = bs.get_guild_settings(interaction.guild_id)

        try:
            bs.remove_cash(interaction.guild_id, interaction.user.id, bet, command="roulette", txn_type="game_bet")
        except EconomyError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return

        result = gs.play_roulette(choice)
        color_emoji = {"red": "🔴", "black": "⚫", "green": "🟢"}
        embed = discord.Embed(title="🎡 Roulette", color=discord.Color.green() if result.won else discord.Color.red())
        embed.add_field(name="Landed on", value=f"{color_emoji[result.landed_color]} {result.landed_number}", inline=True)
        embed.add_field(name="Your bet", value=choice.title(), inline=True)

        if result.won:
            payout = round(bet * result.payout_multiplier)
            bs.add_cash(interaction.guild_id, interaction.user.id, payout, command="roulette", txn_type="game_win")
            embed.add_field(name="Result", value=f"✅ Won **{format_money(payout, settings.currency_symbol)}**", inline=False)
        else:
            embed.add_field(name="Result", value=f"❌ Lost **{format_money(bet, settings.currency_symbol)}**", inline=False)

        await interaction.response.send_message(embed=embed)

    # ---------- blackjack ----------

    @app_commands.command(name="blackjack", description="Play blackjack against the dealer")
    @app_commands.describe(bet="How much to bet")
    async def blackjack(self, interaction: discord.Interaction, bet: int):
        if interaction.user.id in _active_blackjack_games:
            await interaction.response.send_message("🃏 Finish your current hand first.", ephemeral=True)
            return

        if not await _check_cooldown_and_bet(interaction, "blackjack", bet):
            return
        settings = bs.get_guild_settings(interaction.guild_id)

        try:
            bs.remove_cash(interaction.guild_id, interaction.user.id, bet, command="blackjack", txn_type="game_bet")
        except EconomyError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return

        _active_blackjack_games.add(interaction.user.id)
        state = gs.start_blackjack()

        if state.finished:
            await self._resolve_blackjack(interaction, state, bet, settings, first_response=True)
            return

        view = BlackjackView(state, bet, settings, interaction.user.id, self)
        embed = build_blackjack_embed(state, settings, in_progress=True)
        await interaction.response.send_message(embed=embed, view=view)

    async def _resolve_blackjack(self, interaction, state, bet, settings, first_response=False, edit_interaction=None):
        _active_blackjack_games.discard(interaction.user.id)

        if state.payout_multiplier > 0:
            payout = round(bet * state.payout_multiplier)
            bs.add_cash(interaction.guild_id, interaction.user.id, payout, command="blackjack", txn_type="game_win")

        embed = build_blackjack_embed(state, settings, in_progress=False, bet=bet)

        if first_response:
            await interaction.response.send_message(embed=embed)
        elif edit_interaction:
            await edit_interaction.response.edit_message(embed=embed, view=None)


RESULT_LABELS = {
    "player_blackjack": "🃏 Blackjack! You win",
    "dealer_blackjack": "Dealer has Blackjack - you lose",
    "player_bust": "💥 Bust - you lose",
    "dealer_bust": "Dealer busts - you win!",
    "player_win": "✅ You win",
    "dealer_win": "❌ Dealer wins",
    "push": "🤝 Push - bet refunded",
}


def build_blackjack_embed(state, settings, in_progress: bool, bet: int = None) -> discord.Embed:
    player_display = " ".join(state.player_hand)
    dealer_display = " ".join(state.dealer_hand) if not in_progress else f"{state.dealer_hand[0]} 🂠"

    embed = discord.Embed(title="🃏 Blackjack", color=discord.Color.blurple() if in_progress else (
        discord.Color.green() if state.payout_multiplier and state.payout_multiplier > 1 else
        discord.Color.light_grey() if state.result == "push" else discord.Color.red()
    ))
    embed.add_field(name=f"Your hand ({gs.hand_value(state.player_hand)})", value=player_display, inline=False)
    embed.add_field(
        name=f"Dealer's hand{'' if in_progress else f' ({gs.hand_value(state.dealer_hand)})'}",
        value=dealer_display, inline=False,
    )

    if not in_progress:
        embed.add_field(name="Result", value=RESULT_LABELS.get(state.result, state.result), inline=False)
        if bet is not None:
            if state.payout_multiplier > 1:
                payout = round(bet * state.payout_multiplier)
                embed.add_field(name="Payout", value=f"+{format_money(payout, settings.currency_symbol)}", inline=True)
            elif state.payout_multiplier == 1.0:
                embed.add_field(name="Payout", value=f"Refunded {format_money(bet, settings.currency_symbol)}", inline=True)
            else:
                embed.add_field(name="Lost", value=f"-{format_money(bet, settings.currency_symbol)}", inline=True)

    return embed


class BlackjackView(discord.ui.View):
    def __init__(self, state, bet, settings, user_id, cog):
        super().__init__(timeout=60)
        self.state = state
        self.bet = bet
        self.settings = settings
        self.user_id = user_id
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your game.", ephemeral=True)
            return False
        return True

    async def _finish(self, interaction: discord.Interaction):
        self.stop()
        for child in self.children:
            child.disabled = True
        await self.cog._resolve_blackjack(interaction, self.state, self.bet, self.settings, edit_interaction=interaction)

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary, emoji="🃏")
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state = gs.blackjack_hit(self.state)
        if self.state.finished:
            await self._finish(interaction)
        else:
            embed = build_blackjack_embed(self.state, self.settings, in_progress=True)
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary, emoji="✋")
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state = gs.blackjack_stand(self.state)
        await self._finish(interaction)

    async def on_timeout(self):
        _active_blackjack_games.discard(self.user_id)


async def setup(bot: commands.Bot):
    await bot.add_cog(Games(bot))