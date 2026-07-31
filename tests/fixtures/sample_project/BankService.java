import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

/**
 * Demonstrates Java extraction: this adjacent Javadoc is intentionally kept
 * as documentation for the class, while ordinary comments below are removed.
 */
public final class BankService {
    private static final BigDecimal DAILY_LIMIT = new BigDecimal("1000.00");
    private static final String HELP_URL = "https://bank.example/help//transfers";

    /** A simple account with an append-only transaction history. */
    public static final class Account {
        private final String owner;
        private BigDecimal balance = BigDecimal.ZERO;
        private final List<String> history = new ArrayList<>();

        public Account(String owner) {
            this.owner = owner;
        }

        /** Deposits a positive amount and returns the resulting balance. */
        public BigDecimal deposit(BigDecimal amount, String note) {
            // This implementation detail should not be indexed as evidence.
            validatePositive(amount);
            balance = balance.add(amount);
            history.add("deposit " + amount + " " + note);
            return balance;
        }

        public BigDecimal withdraw(BigDecimal amount, String note) {
            validatePositive(amount);
            if (amount.compareTo(balance) > 0) {
                throw new IllegalArgumentException("insufficient funds for " + owner);
            }
            balance = balance.subtract(amount);
            history.add("withdrawal " + amount + " " + note);
            return balance;
        }

        public String summary() {
            return owner + " has " + balance + "; docs: " + HELP_URL;
        }
    }

    /** Transfers a permitted amount and reports both resulting balances. */
    public static String transfer(Account sender, Account recipient, BigDecimal amount) {
        /* A block comment that should also disappear from the code snippet. */
        if (amount.compareTo(DAILY_LIMIT) > 0) {
            throw new IllegalArgumentException("daily limit exceeded");
        }
        sender.withdraw(amount, "outgoing transfer");
        recipient.deposit(amount, "incoming transfer");
        return sender.summary() + " | " + recipient.summary();
    }

    private static void validatePositive(BigDecimal amount) {
        if (amount == null || amount.signum() <= 0) {
            throw new IllegalArgumentException("amount must be positive");
        }
    }

    public static void main(String[] args) {
        Account alice = new Account("Alice");
        Account bob = new Account("Bob");
        alice.deposit(new BigDecimal("125.50"), "initial funding");
        System.out.println(transfer(alice, bob, new BigDecimal("40.25")));
    }
}
