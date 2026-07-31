"""Small in-memory banking example used to exercise RepoProof analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation


# This configuration comment should not become BM25 evidence.
MAX_DAILY_TRANSFER = Decimal("1000.00")
SUPPORT_URL = "https://bank.example/help#transfers"  # `#` is part of the URL string.


def money(value: str | int | Decimal) -> Decimal:
    """Normalize an input amount and reject values with more than two decimals."""
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid money amount: {value!r}") from exc
    if amount < 0:
        raise ValueError("amount cannot be negative")
    return amount


@dataclass
class Transaction:
    """An immutable record for one balance-changing operation."""

    kind: str
    amount: Decimal
    note: str = ""


@dataclass
class Account:
    """A bank account that records deposits, withdrawals, and transfers."""

    owner: str
    balance: Decimal = field(default_factory=lambda: Decimal("0.00"))
    history: list[Transaction] = field(default_factory=list)

    def _record(self, kind: str, amount: Decimal, note: str = "") -> None:
        # Keep the history separate so all public operations share one path.
        self.history.append(Transaction(kind, amount, note))

    def deposit(self, amount: str | int | Decimal, note: str = "") -> Decimal:
        """Add funds and return the new balance."""
        value = money(amount)
        if value == 0:
            raise ValueError("deposit must be positive")
        self.balance += value
        self._record("deposit", value, note)
        return self.balance

    def withdraw(self, amount: str | int | Decimal, note: str = "") -> Decimal:
        """Remove funds if the account can cover the requested amount."""
        value = money(amount)
        if value == 0:
            raise ValueError("withdrawal must be positive")
        if value > self.balance:
            raise ValueError(f"insufficient funds for {self.owner}")
        self.balance -= value
        self._record("withdrawal", value, note)
        return self.balance

    def statement(self) -> str:
        """Return a human-readable transaction summary."""
        rows = [f"{item.kind}: {item.amount} {item.note}".rstrip() for item in self.history]
        return "\n".join([f"Account: {self.owner}", f"Balance: {self.balance}", *rows])


def transfer(sender: Account, recipient: Account, amount: str | int | Decimal,
             reference: str = "") -> tuple[Decimal, Decimal]:
    """Transfer money atomically between two accounts, subject to a daily cap."""
    value = money(amount)
    if sender is recipient:
        raise ValueError("cannot transfer to the same account")
    if value == 0 or value > MAX_DAILY_TRANSFER:
        raise ValueError("transfer must be between 0 and the daily limit")

    # Withdraw first; a failure leaves both accounts unchanged.
    sender.withdraw(value, f"to {recipient.owner}: {reference}")
    recipient.deposit(value, f"from {sender.owner}: {reference}")
    return sender.balance, recipient.balance


if __name__ == "__main__":
    """Create a deterministic sample statement for a quick manual run."""
    alice = Account("Alice")
    bob = Account("Bob")
    alice.deposit("125.50", "initial funding")
    transfer(alice, bob, "40.25", "invoice #2026-07")
    print("Alice's statement:\n" + alice.statement())
    print("Bob's statement:\n" + bob.statement())
