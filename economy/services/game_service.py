"""
Games service - Phase 3.
------------------------------------------
Pure game-outcome logic lives here, separate from the Discord cogs, so it's
fully unit-testable without mocking discord.py.

Uses `secrets` (cryptographically secure) for all randomness, never the
`random` module - per the project spec's requirement for gambling
calculations that can't be exploited/predicted.

House edge is embedded in payout multipliers (e.g. a "fair" 2x coinflip
pays 1.94x instead), not by secretly skewing win probability - this is
standard practice and keeps the odds honest and inspectable.
"""

import secrets
from dataclasses import dataclass, field

from economy.db import SessionLocal
from economy.models import GameConfig

DEFAULT_CONFIGS = {
    "coinflip": {"min_bet": 10, "max_bet": 10_000, "cooldown_seconds": 3},
    "dice": {"min_bet": 10, "max_bet": 10_000, "cooldown_seconds": 3},
    "rps": {"min_bet": 10, "max_bet": 10_000, "cooldown_seconds": 3},
    "slots": {"min_bet": 10, "max_bet": 5_000, "cooldown_seconds": 4},
    "roulette": {"min_bet": 10, "max_bet": 20_000, "cooldown_seconds": 5},
    "blackjack": {"min_bet": 10, "max_bet": 20_000, "cooldown_seconds": 5},
}


def get_game_config(guild_id: int, game: str) -> GameConfig:
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    defaults = DEFAULT_CONFIGS.get(game, {"min_bet": 10, "max_bet": 10_000, "cooldown_seconds": 3})
    with SessionLocal() as session:
        stmt = sqlite_insert(GameConfig).values(guild_id=guild_id, game=game, **defaults).on_conflict_do_nothing(
            index_elements=["guild_id", "game"]
        )
        session.execute(stmt)
        session.commit()
        return session.query(GameConfig).filter_by(guild_id=guild_id, game=game).one()


def set_game_config(guild_id: int, game: str, **kwargs):
    with SessionLocal() as session:
        config = session.query(GameConfig).filter_by(guild_id=guild_id, game=game).one_or_none()
        if config is None:
            defaults = DEFAULT_CONFIGS.get(game, {"min_bet": 10, "max_bet": 10_000, "cooldown_seconds": 3})
            config = GameConfig(guild_id=guild_id, game=game, **defaults)
            session.add(config)
        for key, value in kwargs.items():
            setattr(config, key, value)
        session.commit()


def list_game_configs(guild_id: int) -> list[GameConfig]:
    for game in DEFAULT_CONFIGS:
        get_game_config(guild_id, game)  # ensures every game has a row
    with SessionLocal() as session:
        return session.query(GameConfig).filter_by(guild_id=guild_id).order_by(GameConfig.game).all()


# ---------- secure RNG helpers ----------

def secure_choice(seq):
    return seq[secrets.randbelow(len(seq))]


def secure_randint(a: int, b: int) -> int:
    """Inclusive [a, b], like random.randint but cryptographically secure."""
    return a + secrets.randbelow(b - a + 1)


# ---------- coinflip ----------

@dataclass
class CoinflipResult:
    won: bool
    landed: str  # "heads" | "tails"
    payout_multiplier: float  # applied to the bet if won


def play_coinflip(choice: str) -> CoinflipResult:
    landed = secure_choice(["heads", "tails"])
    won = (landed == choice)
    return CoinflipResult(won=won, landed=landed, payout_multiplier=1.94 if won else 0)


# ---------- dice ----------

@dataclass
class DiceResult:
    won: bool
    rolled: int
    payout_multiplier: float


def play_dice(guess: int) -> DiceResult:
    rolled = secure_randint(1, 6)
    won = (rolled == guess)
    return DiceResult(won=won, rolled=rolled, payout_multiplier=5.5 if won else 0)


# ---------- rock paper scissors ----------

RPS_BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}


@dataclass
class RPSResult:
    outcome: str  # "win" | "lose" | "tie"
    bot_choice: str
    payout_multiplier: float


def play_rps(choice: str) -> RPSResult:
    bot_choice = secure_choice(["rock", "paper", "scissors"])
    if choice == bot_choice:
        return RPSResult(outcome="tie", bot_choice=bot_choice, payout_multiplier=1.0)  # refund, no net change
    if RPS_BEATS[choice] == bot_choice:
        return RPSResult(outcome="win", bot_choice=bot_choice, payout_multiplier=1.94)
    return RPSResult(outcome="lose", bot_choice=bot_choice, payout_multiplier=0)


# ---------- slots ----------

# weight = relative frequency (higher = more common); payout = multiplier for 3-of-a-kind
SLOT_SYMBOLS = [
    {"symbol": "🍒", "weight": 40, "payout": 2},
    {"symbol": "🍋", "weight": 30, "payout": 3},
    {"symbol": "🍇", "weight": 20, "payout": 5},
    {"symbol": "💎", "weight": 8, "payout": 15},
    {"symbol": "7️⃣", "weight": 2, "payout": 50},
]


def _weighted_spin_reel() -> str:
    weights = [s["weight"] for s in SLOT_SYMBOLS]
    total = sum(weights)
    r = secrets.randbelow(total)
    upto = 0
    for s in SLOT_SYMBOLS:
        upto += s["weight"]
        if r < upto:
            return s["symbol"]
    return SLOT_SYMBOLS[-1]["symbol"]  # unreachable in practice


@dataclass
class SlotsResult:
    reels: list = field(default_factory=list)
    won: bool = False
    payout_multiplier: float = 0
    two_match: bool = False


def play_slots() -> SlotsResult:
    reels = [_weighted_spin_reel() for _ in range(3)]
    if reels[0] == reels[1] == reels[2]:
        payout = next(s["payout"] for s in SLOT_SYMBOLS if s["symbol"] == reels[0])
        return SlotsResult(reels=reels, won=True, payout_multiplier=payout)
    if reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
        return SlotsResult(reels=reels, won=True, payout_multiplier=0.5, two_match=True)  # small consolation payout
    return SlotsResult(reels=reels, won=False, payout_multiplier=0)


# ---------- roulette ----------

RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}


def roulette_color(number: int) -> str:
    if number == 0:
        return "green"
    return "red" if number in RED_NUMBERS else "black"


@dataclass
class RouletteResult:
    landed_number: int
    landed_color: str
    won: bool
    payout_multiplier: float


def play_roulette(bet_choice: str) -> RouletteResult:
    """bet_choice is either 'red', 'black', 'green', or a string digit '0'-'36'."""
    landed_number = secure_randint(0, 36)
    landed_color = roulette_color(landed_number)

    if bet_choice in ("red", "black", "green"):
        won = (bet_choice == landed_color)
        multiplier = {"red": 1.94, "black": 1.94, "green": 13.5}[bet_choice] if won else 0
    else:
        won = (str(landed_number) == bet_choice)
        multiplier = 34.0 if won else 0  # true odds 35:1, edge embedded as 34:1

    return RouletteResult(landed_number=landed_number, landed_color=landed_color, won=won, payout_multiplier=multiplier)


# ---------- blackjack ----------

SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]


def new_shuffled_deck() -> list[str]:
    deck = [f"{rank}{suit}" for suit in SUITS for rank in RANKS]
    # Fisher-Yates shuffle using secrets for cryptographic randomness
    for i in range(len(deck) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        deck[i], deck[j] = deck[j], deck[i]
    return deck


def card_rank(card: str) -> str:
    return card[:-1]  # everything except the last character (the suit symbol)


def hand_value(hand: list[str]) -> int:
    total = 0
    aces = 0
    for card in hand:
        rank = card_rank(card)
        if rank == "A":
            total += 11
            aces += 1
        elif rank in ("J", "Q", "K"):
            total += 10
        else:
            total += int(rank)
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


def is_blackjack(hand: list[str]) -> bool:
    return len(hand) == 2 and hand_value(hand) == 21


@dataclass
class BlackjackState:
    deck: list = field(default_factory=new_shuffled_deck)
    player_hand: list = field(default_factory=list)
    dealer_hand: list = field(default_factory=list)
    finished: bool = False
    result: str | None = None  # "player_blackjack" | "dealer_blackjack" | "player_bust" | "dealer_bust" | "player_win" | "dealer_win" | "push"
    payout_multiplier: float = 0


def start_blackjack() -> BlackjackState:
    state = BlackjackState()
    state.player_hand = [state.deck.pop(), state.deck.pop()]
    state.dealer_hand = [state.deck.pop(), state.deck.pop()]

    if is_blackjack(state.player_hand) and is_blackjack(state.dealer_hand):
        state.finished, state.result, state.payout_multiplier = True, "push", 1.0
    elif is_blackjack(state.player_hand):
        state.finished, state.result, state.payout_multiplier = True, "player_blackjack", 2.4  # 3:2 payout, edge embedded
    elif is_blackjack(state.dealer_hand):
        state.finished, state.result, state.payout_multiplier = True, "dealer_blackjack", 0
    return state


def blackjack_hit(state: BlackjackState) -> BlackjackState:
    if state.finished:
        return state
    state.player_hand.append(state.deck.pop())
    if hand_value(state.player_hand) > 21:
        state.finished, state.result, state.payout_multiplier = True, "player_bust", 0
    return state


def blackjack_stand(state: BlackjackState) -> BlackjackState:
    if state.finished:
        return state
    while hand_value(state.dealer_hand) < 17:
        state.dealer_hand.append(state.deck.pop())

    player_total = hand_value(state.player_hand)
    dealer_total = hand_value(state.dealer_hand)

    if dealer_total > 21:
        state.result, state.payout_multiplier = "dealer_bust", 1.94
    elif dealer_total > player_total:
        state.result, state.payout_multiplier = "dealer_win", 0
    elif player_total > dealer_total:
        state.result, state.payout_multiplier = "player_win", 1.94
    else:
        state.result, state.payout_multiplier = "push", 1.0

    state.finished = True
    return state