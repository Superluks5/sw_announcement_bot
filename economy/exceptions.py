class EconomyError(Exception):
    """Base class for economy errors - cogs catch this to show a clean
    Discord message instead of a raw traceback."""


class InvalidAmountError(EconomyError):
    def __init__(self, message: str = "Amount must be a positive whole number."):
        super().__init__(message)


class InsufficientFundsError(EconomyError):
    def __init__(self, message: str = "Insufficient funds."):
        super().__init__(message)


class BalanceLimitError(EconomyError):
    def __init__(self, message: str = "That would exceed the server's maximum balance."):
        super().__init__(message)
