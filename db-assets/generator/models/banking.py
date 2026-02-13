"""Banking domain models (60 tables).

Categories:
- Accounts (12): accounts, account_types, account_holders, joint_accounts, savings_accounts,
                 checking_accounts, money_market_accounts, certificates_of_deposit, account_beneficiaries,
                 account_statements, account_alerts, account_limits
- Transactions (15): transactions, transaction_types, transfers, standing_orders, scheduled_payments,
                     wire_transfers, ach_transfers, check_deposits, atm_transactions, pos_transactions,
                     transaction_disputes, transaction_categories, transaction_tags, recurring_transactions,
                     transaction_fees
- Cards (10): credit_cards, debit_cards, card_transactions, card_limits, card_rewards,
              card_rewards_redemptions, card_statements, virtual_cards, card_controls, card_disputes
- Loans (12): loans, loan_types, loan_applications, loan_payments, loan_schedules, collateral,
              guarantors, loan_documents, loan_officers, loan_status_history, loan_fees, loan_refinancing
- Compliance (6): kyc_documents, aml_checks, sanctions_screening, suspicious_activity_reports,
                  compliance_cases, regulatory_reports
- Users (5): bank_users, user_sessions_bank, login_history_bank, security_questions, trusted_devices
"""

from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, Numeric, Date,
    ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship

from .base import Base, TimestampMixin, AuditMixin


# ============================================================================
# Accounts (12 tables)
# ============================================================================

class AccountType(Base, TimestampMixin):
    """Account type definitions."""
    __tablename__ = 'account_types'

    type_id = Column(Integer, primary_key=True, autoincrement=True)
    type_code = Column(String(20), nullable=False, unique=True)
    type_name = Column(String(100), nullable=False)
    description = Column(Text)
    category = Column(String(50))  # CHECKING, SAVINGS, INVESTMENT, LOAN
    min_balance = Column(Numeric(14, 2), default=0)
    monthly_fee = Column(Numeric(10, 2), default=0)
    interest_rate = Column(Numeric(6, 4), default=0)
    is_active = Column(Boolean, default=True)


class Account(Base, AuditMixin):
    """Bank accounts."""
    __tablename__ = 'accounts'

    account_id = Column(Integer, primary_key=True, autoincrement=True)
    account_number = Column(String(20), nullable=False, unique=True)
    routing_number = Column(String(9), nullable=False)
    account_type_id = Column(Integer, ForeignKey('account_types.type_id'), nullable=False)
    account_name = Column(String(100))
    status = Column(String(20), nullable=False)  # ACTIVE, DORMANT, FROZEN, CLOSED
    opened_date = Column(Date, nullable=False)
    closed_date = Column(Date)
    current_balance = Column(Numeric(14, 2), nullable=False, default=0)
    available_balance = Column(Numeric(14, 2), nullable=False, default=0)
    pending_balance = Column(Numeric(14, 2), default=0)
    currency_code = Column(String(3), default='USD')
    interest_rate = Column(Numeric(6, 4))
    last_activity_date = Column(DateTime)
    overdraft_protection = Column(Boolean, default=False)
    overdraft_limit = Column(Numeric(14, 2), default=0)

    # Relationships
    holders = relationship("AccountHolder", back_populates="account")
    transactions = relationship("BankTransaction", back_populates="account")
    statements = relationship("AccountStatement", back_populates="account")
    alerts = relationship("AccountAlert", back_populates="account")

    __table_args__ = (
        Index('ix_accounts_account_number', 'account_number'),
    )


class AccountHolder(Base, AuditMixin):
    """Account holders (customers linked to accounts)."""
    __tablename__ = 'account_holders'

    holder_id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('accounts.account_id'), nullable=False)
    customer_id = Column(Integer, nullable=False)  # Links to customers table
    holder_type = Column(String(20), nullable=False)  # PRIMARY, JOINT, AUTHORIZED
    relationship_type = Column(String(50))
    ownership_percentage = Column(Numeric(5, 2), default=100)
    signing_authority = Column(Boolean, default=True)
    added_date = Column(Date, nullable=False)
    removed_date = Column(Date)

    # Relationships
    account = relationship("Account", back_populates="holders")

    __table_args__ = (
        UniqueConstraint('account_id', 'customer_id', name='uq_account_holder'),
    )


class JointAccount(Base, TimestampMixin):
    """Joint account configuration."""
    __tablename__ = 'joint_accounts'

    joint_id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('accounts.account_id'), nullable=False, unique=True)
    survivorship_type = Column(String(50))  # RIGHTS_OF_SURVIVORSHIP, TENANTS_IN_COMMON
    signature_requirement = Column(String(20))  # ANY, ALL, THRESHOLD
    signature_threshold = Column(Integer, default=1)


class SavingsAccount(Base, TimestampMixin):
    """Savings account specific details."""
    __tablename__ = 'savings_accounts'

    savings_id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('accounts.account_id'), nullable=False, unique=True)
    interest_rate = Column(Numeric(6, 4), nullable=False)
    compound_frequency = Column(String(20))  # DAILY, MONTHLY, QUARTERLY
    withdrawal_limit = Column(Integer, default=6)
    withdrawals_this_period = Column(Integer, default=0)
    last_interest_date = Column(Date)
    accrued_interest = Column(Numeric(14, 2), default=0)


class CheckingAccount(Base, TimestampMixin):
    """Checking account specific details."""
    __tablename__ = 'checking_accounts'

    checking_id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('accounts.account_id'), nullable=False, unique=True)
    check_number_sequence = Column(Integer, default=1001)
    overdraft_linked_account = Column(Integer, ForeignKey('accounts.account_id'))
    free_checks_monthly = Column(Integer, default=0)
    debit_card_id = Column(Integer)


class MoneyMarketAccount(Base, TimestampMixin):
    """Money market account details."""
    __tablename__ = 'money_market_accounts'

    mm_id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('accounts.account_id'), nullable=False, unique=True)
    tier_balance = Column(Numeric(14, 2), nullable=False)
    tiered_rate = Column(Numeric(6, 4), nullable=False)
    check_writing_enabled = Column(Boolean, default=True)
    min_check_amount = Column(Numeric(14, 2))


class CertificateOfDeposit(Base, AuditMixin):
    """Certificates of Deposit (CDs)."""
    __tablename__ = 'certificates_of_deposit'

    cd_id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('accounts.account_id'), nullable=False)
    principal_amount = Column(Numeric(14, 2), nullable=False)
    interest_rate = Column(Numeric(6, 4), nullable=False)
    term_months = Column(Integer, nullable=False)
    start_date = Column(Date, nullable=False)
    maturity_date = Column(Date, nullable=False)
    auto_renew = Column(Boolean, default=False)
    renewal_term_months = Column(Integer)
    early_withdrawal_penalty = Column(Numeric(6, 4))
    accrued_interest = Column(Numeric(14, 2), default=0)
    status = Column(String(20), nullable=False)  # ACTIVE, MATURED, RENEWED, CLOSED


class AccountBeneficiary(Base, TimestampMixin):
    """Account beneficiaries for POD/TOD."""
    __tablename__ = 'account_beneficiaries'

    beneficiary_id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('accounts.account_id'), nullable=False)
    beneficiary_name = Column(String(200), nullable=False)
    beneficiary_type = Column(String(20))  # PRIMARY, CONTINGENT
    percentage = Column(Numeric(5, 2), nullable=False)
    relationship = Column(String(50))
    date_of_birth = Column(Date)
    ssn_last_four = Column(String(4))
    address = Column(Text)


class AccountStatement(Base, TimestampMixin):
    """Account statements."""
    __tablename__ = 'account_statements'

    statement_id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('accounts.account_id'), nullable=False)
    statement_date = Column(Date, nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    opening_balance = Column(Numeric(14, 2), nullable=False)
    closing_balance = Column(Numeric(14, 2), nullable=False)
    total_deposits = Column(Numeric(14, 2), default=0)
    total_withdrawals = Column(Numeric(14, 2), default=0)
    interest_earned = Column(Numeric(14, 2), default=0)
    fees_charged = Column(Numeric(14, 2), default=0)
    document_url = Column(String(500))

    # Relationships
    account = relationship("Account", back_populates="statements")

    __table_args__ = (
        UniqueConstraint('account_id', 'statement_date', name='uq_account_statement'),
    )


class AccountAlert(Base, AuditMixin):
    """Account alerts configuration."""
    __tablename__ = 'account_alerts'

    alert_id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('accounts.account_id'), nullable=False)
    alert_type = Column(String(50), nullable=False)  # LOW_BALANCE, LARGE_TRANSACTION, DEPOSIT
    threshold_amount = Column(Numeric(14, 2))
    delivery_method = Column(String(20))  # EMAIL, SMS, PUSH
    delivery_address = Column(String(255))
    is_enabled = Column(Boolean, default=True)

    # Relationships
    account = relationship("Account", back_populates="alerts")


class AccountLimit(Base, TimestampMixin):
    """Account transaction limits."""
    __tablename__ = 'account_limits'

    limit_id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('accounts.account_id'), nullable=False)
    limit_type = Column(String(50), nullable=False)  # DAILY_WITHDRAWAL, DAILY_TRANSFER, PER_TRANSACTION
    limit_amount = Column(Numeric(14, 2), nullable=False)
    current_usage = Column(Numeric(14, 2), default=0)
    reset_period = Column(String(20))  # DAILY, WEEKLY, MONTHLY
    last_reset_date = Column(Date)

    __table_args__ = (
        UniqueConstraint('account_id', 'limit_type', name='uq_account_limit'),
    )


# ============================================================================
# Transactions (15 tables)
# ============================================================================

class TransactionType(Base, TimestampMixin):
    """Transaction type definitions."""
    __tablename__ = 'transaction_types'

    type_id = Column(Integer, primary_key=True, autoincrement=True)
    type_code = Column(String(20), nullable=False, unique=True)
    type_name = Column(String(100), nullable=False)
    category = Column(String(50))  # DEBIT, CREDIT, FEE, INTEREST
    description = Column(Text)


class BankTransaction(Base, TimestampMixin):
    """Bank account transactions."""
    __tablename__ = 'bank_transactions'

    transaction_id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('accounts.account_id'), nullable=False)
    transaction_type_id = Column(Integer, ForeignKey('transaction_types.type_id'), nullable=False)
    reference_number = Column(String(50), nullable=False, unique=True)
    transaction_date = Column(DateTime, nullable=False)
    posting_date = Column(DateTime)
    amount = Column(Numeric(14, 2), nullable=False)
    running_balance = Column(Numeric(14, 2))
    description = Column(String(255))
    memo = Column(Text)
    channel = Column(String(20))  # BRANCH, ATM, ONLINE, MOBILE, ACH
    status = Column(String(20), nullable=False)  # PENDING, POSTED, REVERSED, FAILED
    counterparty_name = Column(String(200))
    counterparty_account = Column(String(50))
    check_number = Column(String(20))
    location = Column(String(200))
    merchant_category_code = Column(String(10))

    # Relationships
    account = relationship("Account", back_populates="transactions")

    __table_args__ = (
        Index('ix_bank_transactions_account_id', 'account_id'),
        Index('ix_bank_transactions_date', 'transaction_date'),
    )


class Transfer(Base, AuditMixin):
    """Internal and external transfers."""
    __tablename__ = 'transfers'

    transfer_id = Column(Integer, primary_key=True, autoincrement=True)
    from_account_id = Column(Integer, ForeignKey('accounts.account_id'), nullable=False)
    to_account_id = Column(Integer, ForeignKey('accounts.account_id'))
    external_account = Column(String(50))
    external_routing = Column(String(9))
    external_bank_name = Column(String(100))
    amount = Column(Numeric(14, 2), nullable=False)
    currency_code = Column(String(3), default='USD')
    transfer_type = Column(String(20), nullable=False)  # INTERNAL, ACH, WIRE
    scheduled_date = Column(Date)
    executed_date = Column(DateTime)
    status = Column(String(20), nullable=False)
    reference_number = Column(String(50), unique=True)
    memo = Column(String(255))
    initiated_by = Column(Integer)


class StandingOrder(Base, AuditMixin):
    """Standing orders for recurring transfers."""
    __tablename__ = 'standing_orders'

    order_id = Column(Integer, primary_key=True, autoincrement=True)
    from_account_id = Column(Integer, ForeignKey('accounts.account_id'), nullable=False)
    to_account_id = Column(Integer, ForeignKey('accounts.account_id'))
    payee_id = Column(Integer)
    amount = Column(Numeric(14, 2), nullable=False)
    frequency = Column(String(20), nullable=False)  # WEEKLY, BIWEEKLY, MONTHLY
    start_date = Column(Date, nullable=False)
    end_date = Column(Date)
    next_execution_date = Column(Date)
    last_execution_date = Column(Date)
    execution_count = Column(Integer, default=0)
    status = Column(String(20), nullable=False)
    description = Column(String(255))


class ScheduledPayment(Base, AuditMixin):
    """Scheduled one-time payments."""
    __tablename__ = 'scheduled_payments'

    payment_id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('accounts.account_id'), nullable=False)
    payee_id = Column(Integer)
    payee_name = Column(String(200))
    amount = Column(Numeric(14, 2), nullable=False)
    scheduled_date = Column(Date, nullable=False)
    payment_method = Column(String(20))  # ACH, CHECK, WIRE
    memo = Column(String(255))
    status = Column(String(20), nullable=False)
    executed_date = Column(DateTime)
    confirmation_number = Column(String(50))


class WireTransfer(Base, AuditMixin):
    """Wire transfer details."""
    __tablename__ = 'wire_transfers'

    wire_id = Column(Integer, primary_key=True, autoincrement=True)
    transfer_id = Column(Integer, ForeignKey('transfers.transfer_id'), nullable=False)
    wire_type = Column(String(20), nullable=False)  # DOMESTIC, INTERNATIONAL
    beneficiary_name = Column(String(200), nullable=False)
    beneficiary_address = Column(Text)
    beneficiary_bank_name = Column(String(200))
    beneficiary_bank_address = Column(Text)
    swift_code = Column(String(11))
    iban = Column(String(34))
    intermediary_bank = Column(String(200))
    intermediary_swift = Column(String(11))
    purpose = Column(String(255))
    fee_amount = Column(Numeric(10, 2))
    exchange_rate = Column(Numeric(12, 6))


class AchTransfer(Base, AuditMixin):
    """ACH transfer details."""
    __tablename__ = 'ach_transfers'

    ach_id = Column(Integer, primary_key=True, autoincrement=True)
    transfer_id = Column(Integer, ForeignKey('transfers.transfer_id'), nullable=False)
    sec_code = Column(String(3), nullable=False)  # PPD, CCD, WEB, TEL
    company_name = Column(String(100))
    company_id = Column(String(20))
    individual_name = Column(String(100))
    individual_id = Column(String(20))
    trace_number = Column(String(20))
    settlement_date = Column(Date)
    return_code = Column(String(10))
    return_reason = Column(String(255))


class CheckDeposit(Base, TimestampMixin):
    """Check deposit details."""
    __tablename__ = 'check_deposits'

    deposit_id = Column(Integer, primary_key=True, autoincrement=True)
    transaction_id = Column(Integer, ForeignKey('bank_transactions.transaction_id'), nullable=False)
    check_number = Column(String(20))
    check_amount = Column(Numeric(14, 2), nullable=False)
    payer_name = Column(String(200))
    payer_routing = Column(String(9))
    payer_account = Column(String(20))
    deposit_method = Column(String(20))  # BRANCH, ATM, MOBILE
    front_image_url = Column(String(500))
    back_image_url = Column(String(500))
    hold_amount = Column(Numeric(14, 2), default=0)
    hold_release_date = Column(Date)
    verification_status = Column(String(20))


class AtmTransaction(Base, TimestampMixin):
    """ATM transaction details."""
    __tablename__ = 'atm_transactions'

    atm_txn_id = Column(Integer, primary_key=True, autoincrement=True)
    transaction_id = Column(Integer, ForeignKey('bank_transactions.transaction_id'), nullable=False)
    atm_id = Column(String(50))
    atm_location = Column(String(200))
    atm_owner = Column(String(100))
    transaction_type = Column(String(20))  # WITHDRAWAL, DEPOSIT, BALANCE, TRANSFER
    surcharge_amount = Column(Numeric(10, 2), default=0)
    surcharge_rebated = Column(Boolean, default=False)
    card_used = Column(String(20))


class PosTransaction(Base, TimestampMixin):
    """POS transaction details."""
    __tablename__ = 'pos_transactions'

    pos_txn_id = Column(Integer, primary_key=True, autoincrement=True)
    transaction_id = Column(Integer, ForeignKey('bank_transactions.transaction_id'), nullable=False)
    merchant_id = Column(String(50))
    merchant_name = Column(String(200))
    merchant_category = Column(String(100))
    merchant_city = Column(String(100))
    merchant_state = Column(String(50))
    merchant_country = Column(String(3))
    terminal_id = Column(String(50))
    entry_mode = Column(String(20))  # CHIP, SWIPE, CONTACTLESS, MANUAL
    authorization_code = Column(String(20))
    cashback_amount = Column(Numeric(10, 2), default=0)


class TransactionDispute(Base, AuditMixin):
    """Transaction disputes."""
    __tablename__ = 'transaction_disputes'

    dispute_id = Column(Integer, primary_key=True, autoincrement=True)
    transaction_id = Column(Integer, ForeignKey('bank_transactions.transaction_id'), nullable=False)
    dispute_type = Column(String(50), nullable=False)
    dispute_reason = Column(Text, nullable=False)
    disputed_amount = Column(Numeric(14, 2), nullable=False)
    status = Column(String(20), nullable=False)
    filed_date = Column(Date, nullable=False)
    resolved_date = Column(Date)
    resolution = Column(String(50))
    credit_issued = Column(Numeric(14, 2))
    investigator_notes = Column(Text)


class TransactionCategory(Base, TimestampMixin):
    """User-defined transaction categories."""
    __tablename__ = 'bank_transaction_categories'

    category_id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=False)
    category_name = Column(String(50), nullable=False)
    parent_category_id = Column(Integer, ForeignKey('bank_transaction_categories.category_id'))
    icon = Column(String(50))
    color = Column(String(7))
    budget_amount = Column(Numeric(14, 2))


class TransactionTag(Base, TimestampMixin):
    """Tags for transactions."""
    __tablename__ = 'bank_transaction_tags'

    tag_id = Column(Integer, primary_key=True, autoincrement=True)
    transaction_id = Column(Integer, ForeignKey('bank_transactions.transaction_id'), nullable=False)
    category_id = Column(Integer, ForeignKey('bank_transaction_categories.category_id'))
    tag_name = Column(String(50))
    notes = Column(Text)


class RecurringTransaction(Base, TimestampMixin):
    """Detected recurring transactions."""
    __tablename__ = 'recurring_transactions'

    recurring_id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('accounts.account_id'), nullable=False)
    merchant_pattern = Column(String(200), nullable=False)
    average_amount = Column(Numeric(14, 2))
    frequency_days = Column(Integer)
    next_expected_date = Column(Date)
    last_transaction_id = Column(Integer, ForeignKey('bank_transactions.transaction_id'))
    is_confirmed = Column(Boolean, default=False)


class TransactionFee(Base, TimestampMixin):
    """Transaction fees."""
    __tablename__ = 'transaction_fees'

    fee_id = Column(Integer, primary_key=True, autoincrement=True)
    transaction_id = Column(Integer, ForeignKey('bank_transactions.transaction_id'), nullable=False)
    fee_type = Column(String(50), nullable=False)
    fee_amount = Column(Numeric(10, 2), nullable=False)
    waived = Column(Boolean, default=False)
    waived_reason = Column(String(255))


# ============================================================================
# Cards (10 tables)
# ============================================================================

class CreditCard(Base, AuditMixin):
    """Credit cards."""
    __tablename__ = 'credit_cards'

    card_id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('accounts.account_id'), nullable=False)
    card_number = Column(String(16), nullable=False)
    card_type = Column(String(20), nullable=False)  # VISA, MASTERCARD, AMEX, DISCOVER
    cardholder_name = Column(String(100), nullable=False)
    expiry_month = Column(Integer, nullable=False)
    expiry_year = Column(Integer, nullable=False)
    cvv = Column(String(4))
    credit_limit = Column(Numeric(14, 2), nullable=False)
    available_credit = Column(Numeric(14, 2), nullable=False)
    current_balance = Column(Numeric(14, 2), default=0)
    statement_balance = Column(Numeric(14, 2), default=0)
    minimum_payment = Column(Numeric(14, 2), default=0)
    payment_due_date = Column(Date)
    apr = Column(Numeric(5, 2))
    cash_advance_apr = Column(Numeric(5, 2))
    annual_fee = Column(Numeric(10, 2), default=0)
    status = Column(String(20), nullable=False)
    issued_date = Column(Date)
    last_four = Column(String(4))

    __table_args__ = (
        Index('ix_credit_cards_last_four', 'last_four'),
    )


class DebitCard(Base, AuditMixin):
    """Debit cards linked to checking accounts."""
    __tablename__ = 'debit_cards'

    card_id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('accounts.account_id'), nullable=False)
    card_number = Column(String(16), nullable=False)
    card_type = Column(String(20), nullable=False)
    cardholder_name = Column(String(100), nullable=False)
    expiry_month = Column(Integer, nullable=False)
    expiry_year = Column(Integer, nullable=False)
    pin_hash = Column(String(255))
    daily_limit = Column(Numeric(14, 2))
    atm_limit = Column(Numeric(14, 2))
    pos_limit = Column(Numeric(14, 2))
    status = Column(String(20), nullable=False)
    issued_date = Column(Date)
    last_four = Column(String(4))


class CardTransaction(Base, TimestampMixin):
    """Card-specific transactions (credit and debit)."""
    __tablename__ = 'card_transactions'

    card_txn_id = Column(Integer, primary_key=True, autoincrement=True)
    card_id = Column(Integer, nullable=False)  # Can be credit or debit
    card_type = Column(String(10), nullable=False)  # CREDIT, DEBIT
    transaction_date = Column(DateTime, nullable=False)
    posting_date = Column(DateTime)
    merchant_name = Column(String(200))
    merchant_category_code = Column(String(10))
    amount = Column(Numeric(14, 2), nullable=False)
    currency_code = Column(String(3), default='USD')
    transaction_type = Column(String(20))  # PURCHASE, RETURN, CASH_ADVANCE, FEE
    authorization_code = Column(String(20))
    status = Column(String(20), nullable=False)
    foreign_amount = Column(Numeric(14, 2))
    foreign_currency = Column(String(3))
    exchange_rate = Column(Numeric(12, 6))

    __table_args__ = (
        Index('ix_card_transactions_card_id', 'card_id'),
    )


class CardLimit(Base, TimestampMixin):
    """Card spending limits."""
    __tablename__ = 'card_limits'

    limit_id = Column(Integer, primary_key=True, autoincrement=True)
    card_id = Column(Integer, nullable=False)
    card_type = Column(String(10), nullable=False)
    limit_type = Column(String(50), nullable=False)
    limit_amount = Column(Numeric(14, 2), nullable=False)
    current_usage = Column(Numeric(14, 2), default=0)
    period = Column(String(20))  # DAILY, WEEKLY, MONTHLY


class CardReward(Base, TimestampMixin):
    """Card rewards programs."""
    __tablename__ = 'card_rewards'

    reward_id = Column(Integer, primary_key=True, autoincrement=True)
    card_id = Column(Integer, nullable=False)
    reward_type = Column(String(50), nullable=False)  # CASHBACK, POINTS, MILES
    current_balance = Column(Numeric(14, 2), default=0)
    lifetime_earned = Column(Numeric(14, 2), default=0)
    lifetime_redeemed = Column(Numeric(14, 2), default=0)
    expiring_amount = Column(Numeric(14, 2), default=0)
    expiry_date = Column(Date)


class CardRewardRedemption(Base, TimestampMixin):
    """Card reward redemptions."""
    __tablename__ = 'card_reward_redemptions'

    redemption_id = Column(Integer, primary_key=True, autoincrement=True)
    reward_id = Column(Integer, ForeignKey('card_rewards.reward_id'), nullable=False)
    redemption_type = Column(String(50), nullable=False)  # STATEMENT_CREDIT, GIFT_CARD, TRAVEL
    points_redeemed = Column(Numeric(14, 2), nullable=False)
    dollar_value = Column(Numeric(14, 2), nullable=False)
    redemption_date = Column(DateTime, nullable=False)
    status = Column(String(20), nullable=False)
    details = Column(Text)


class CardStatement(Base, TimestampMixin):
    """Credit card statements."""
    __tablename__ = 'card_statements'

    statement_id = Column(Integer, primary_key=True, autoincrement=True)
    card_id = Column(Integer, ForeignKey('credit_cards.card_id'), nullable=False)
    statement_date = Column(Date, nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    previous_balance = Column(Numeric(14, 2))
    payments = Column(Numeric(14, 2))
    purchases = Column(Numeric(14, 2))
    cash_advances = Column(Numeric(14, 2))
    fees = Column(Numeric(14, 2))
    interest = Column(Numeric(14, 2))
    new_balance = Column(Numeric(14, 2), nullable=False)
    minimum_payment = Column(Numeric(14, 2))
    payment_due_date = Column(Date)
    credit_limit = Column(Numeric(14, 2))
    available_credit = Column(Numeric(14, 2))


class VirtualCard(Base, AuditMixin):
    """Virtual card numbers."""
    __tablename__ = 'virtual_cards'

    virtual_card_id = Column(Integer, primary_key=True, autoincrement=True)
    physical_card_id = Column(Integer, nullable=False)
    card_number = Column(String(16), nullable=False)
    expiry_month = Column(Integer, nullable=False)
    expiry_year = Column(Integer, nullable=False)
    cvv = Column(String(4))
    spending_limit = Column(Numeric(14, 2))
    merchant_lock = Column(String(200))
    valid_from = Column(DateTime)
    valid_until = Column(DateTime)
    status = Column(String(20), nullable=False)
    usage_count = Column(Integer, default=0)


class CardControl(Base, AuditMixin):
    """Card controls and restrictions."""
    __tablename__ = 'card_controls'

    control_id = Column(Integer, primary_key=True, autoincrement=True)
    card_id = Column(Integer, nullable=False)
    card_type = Column(String(10), nullable=False)
    control_type = Column(String(50), nullable=False)  # GEOGRAPHIC, MERCHANT, TIME, AMOUNT
    control_value = Column(Text)
    is_enabled = Column(Boolean, default=True)


class CardDispute(Base, AuditMixin):
    """Credit/debit card disputes."""
    __tablename__ = 'card_disputes'

    dispute_id = Column(Integer, primary_key=True, autoincrement=True)
    card_txn_id = Column(Integer, ForeignKey('card_transactions.card_txn_id'), nullable=False)
    dispute_type = Column(String(50), nullable=False)
    reason_code = Column(String(20))
    disputed_amount = Column(Numeric(14, 2), nullable=False)
    provisional_credit = Column(Numeric(14, 2))
    status = Column(String(20), nullable=False)
    filed_date = Column(Date, nullable=False)
    deadline_date = Column(Date)
    resolved_date = Column(Date)
    resolution = Column(String(50))
    merchant_response = Column(Text)


# ============================================================================
# Loans (12 tables)
# ============================================================================

class LoanType(Base, TimestampMixin):
    """Loan type definitions."""
    __tablename__ = 'loan_types'

    type_id = Column(Integer, primary_key=True, autoincrement=True)
    type_code = Column(String(20), nullable=False, unique=True)
    type_name = Column(String(100), nullable=False)
    category = Column(String(50))  # MORTGAGE, AUTO, PERSONAL, STUDENT, BUSINESS
    min_amount = Column(Numeric(14, 2))
    max_amount = Column(Numeric(14, 2))
    min_term_months = Column(Integer)
    max_term_months = Column(Integer)
    base_rate = Column(Numeric(6, 4))
    requires_collateral = Column(Boolean, default=False)


class Loan(Base, AuditMixin):
    """Loans."""
    __tablename__ = 'loans'

    loan_id = Column(Integer, primary_key=True, autoincrement=True)
    loan_number = Column(String(20), nullable=False, unique=True)
    account_id = Column(Integer, ForeignKey('accounts.account_id'), nullable=False)
    loan_type_id = Column(Integer, ForeignKey('loan_types.type_id'), nullable=False)
    borrower_id = Column(Integer, nullable=False)
    original_amount = Column(Numeric(14, 2), nullable=False)
    current_balance = Column(Numeric(14, 2), nullable=False)
    interest_rate = Column(Numeric(6, 4), nullable=False)
    rate_type = Column(String(20))  # FIXED, VARIABLE
    term_months = Column(Integer, nullable=False)
    monthly_payment = Column(Numeric(14, 2), nullable=False)
    origination_date = Column(Date, nullable=False)
    first_payment_date = Column(Date, nullable=False)
    maturity_date = Column(Date, nullable=False)
    next_payment_date = Column(Date)
    last_payment_date = Column(Date)
    status = Column(String(20), nullable=False)
    days_past_due = Column(Integer, default=0)
    origination_fee = Column(Numeric(14, 2))


class LoanApplication(Base, AuditMixin):
    """Loan applications."""
    __tablename__ = 'loan_applications'

    application_id = Column(Integer, primary_key=True, autoincrement=True)
    application_number = Column(String(20), nullable=False, unique=True)
    loan_type_id = Column(Integer, ForeignKey('loan_types.type_id'), nullable=False)
    applicant_id = Column(Integer, nullable=False)
    co_applicant_id = Column(Integer)
    requested_amount = Column(Numeric(14, 2), nullable=False)
    requested_term = Column(Integer)
    purpose = Column(String(255))
    employment_status = Column(String(50))
    annual_income = Column(Numeric(14, 2))
    monthly_expenses = Column(Numeric(14, 2))
    credit_score = Column(Integer)
    debt_to_income = Column(Numeric(5, 2))
    status = Column(String(20), nullable=False)
    submitted_date = Column(DateTime, nullable=False)
    decision_date = Column(DateTime)
    approved_amount = Column(Numeric(14, 2))
    approved_rate = Column(Numeric(6, 4))
    decline_reason = Column(String(255))
    loan_officer_id = Column(Integer, ForeignKey('loan_officers.officer_id'))


class LoanPayment(Base, TimestampMixin):
    """Loan payments."""
    __tablename__ = 'loan_payments'

    payment_id = Column(Integer, primary_key=True, autoincrement=True)
    loan_id = Column(Integer, ForeignKey('loans.loan_id'), nullable=False)
    payment_date = Column(DateTime, nullable=False)
    due_date = Column(Date, nullable=False)
    scheduled_amount = Column(Numeric(14, 2), nullable=False)
    actual_amount = Column(Numeric(14, 2), nullable=False)
    principal_amount = Column(Numeric(14, 2))
    interest_amount = Column(Numeric(14, 2))
    escrow_amount = Column(Numeric(14, 2))
    fees_amount = Column(Numeric(14, 2))
    payment_method = Column(String(20))
    confirmation_number = Column(String(50))
    status = Column(String(20), nullable=False)
    balance_after = Column(Numeric(14, 2))


class LoanSchedule(Base, TimestampMixin):
    """Loan amortization schedule."""
    __tablename__ = 'loan_schedules'

    schedule_id = Column(Integer, primary_key=True, autoincrement=True)
    loan_id = Column(Integer, ForeignKey('loans.loan_id'), nullable=False)
    payment_number = Column(Integer, nullable=False)
    due_date = Column(Date, nullable=False)
    payment_amount = Column(Numeric(14, 2), nullable=False)
    principal_amount = Column(Numeric(14, 2), nullable=False)
    interest_amount = Column(Numeric(14, 2), nullable=False)
    escrow_amount = Column(Numeric(14, 2))
    balance_after = Column(Numeric(14, 2), nullable=False)
    is_paid = Column(Boolean, default=False)
    paid_date = Column(Date)

    __table_args__ = (
        UniqueConstraint('loan_id', 'payment_number', name='uq_loan_schedule'),
    )


class Collateral(Base, AuditMixin):
    """Loan collateral."""
    __tablename__ = 'collateral'

    collateral_id = Column(Integer, primary_key=True, autoincrement=True)
    loan_id = Column(Integer, ForeignKey('loans.loan_id'), nullable=False)
    collateral_type = Column(String(50), nullable=False)  # REAL_ESTATE, VEHICLE, EQUIPMENT, SECURITIES
    description = Column(Text)
    estimated_value = Column(Numeric(14, 2), nullable=False)
    valuation_date = Column(Date)
    lien_position = Column(Integer, default=1)
    insurance_required = Column(Boolean, default=True)
    insurance_verified = Column(Boolean, default=False)
    property_address = Column(Text)
    vin = Column(String(20))
    title_number = Column(String(50))


class Guarantor(Base, AuditMixin):
    """Loan guarantors."""
    __tablename__ = 'guarantors'

    guarantor_id = Column(Integer, primary_key=True, autoincrement=True)
    loan_id = Column(Integer, ForeignKey('loans.loan_id'), nullable=False)
    person_id = Column(Integer, nullable=False)
    relationship = Column(String(50))
    guarantee_type = Column(String(50))  # FULL, LIMITED
    guarantee_amount = Column(Numeric(14, 2))
    guarantee_percentage = Column(Numeric(5, 2))
    signed_date = Column(Date)
    document_id = Column(Integer)


class LoanDocument(Base, TimestampMixin):
    """Loan documents."""
    __tablename__ = 'loan_documents'

    document_id = Column(Integer, primary_key=True, autoincrement=True)
    loan_id = Column(Integer, ForeignKey('loans.loan_id'))
    application_id = Column(Integer, ForeignKey('loan_applications.application_id'))
    document_type = Column(String(50), nullable=False)
    document_name = Column(String(255), nullable=False)
    file_path = Column(String(500))
    file_size = Column(Integer)
    uploaded_date = Column(DateTime, nullable=False)
    uploaded_by = Column(Integer)
    verified = Column(Boolean, default=False)
    verified_by = Column(Integer)
    verified_date = Column(DateTime)


class LoanOfficer(Base, AuditMixin):
    """Loan officers."""
    __tablename__ = 'loan_officers'

    officer_id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(String(20), nullable=False, unique=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(255))
    phone = Column(String(20))
    nmls_id = Column(String(20))
    branch = Column(String(100))
    specialization = Column(String(100))
    hire_date = Column(Date)
    status = Column(String(20), nullable=False)


class LoanStatusHistory(Base):
    """Loan status change history."""
    __tablename__ = 'loan_status_history'

    history_id = Column(Integer, primary_key=True, autoincrement=True)
    loan_id = Column(Integer, ForeignKey('loans.loan_id'), nullable=False)
    previous_status = Column(String(20))
    new_status = Column(String(20), nullable=False)
    changed_date = Column(DateTime, nullable=False)
    changed_by = Column(Integer)
    notes = Column(Text)


class LoanFee(Base, TimestampMixin):
    """Loan fees."""
    __tablename__ = 'loan_fees'

    fee_id = Column(Integer, primary_key=True, autoincrement=True)
    loan_id = Column(Integer, ForeignKey('loans.loan_id'), nullable=False)
    fee_type = Column(String(50), nullable=False)
    fee_amount = Column(Numeric(14, 2), nullable=False)
    assessed_date = Column(Date, nullable=False)
    due_date = Column(Date)
    paid_date = Column(Date)
    waived = Column(Boolean, default=False)
    waived_reason = Column(String(255))


class LoanRefinancing(Base, AuditMixin):
    """Loan refinancing records."""
    __tablename__ = 'loan_refinancing'

    refinance_id = Column(Integer, primary_key=True, autoincrement=True)
    original_loan_id = Column(Integer, ForeignKey('loans.loan_id'), nullable=False)
    new_loan_id = Column(Integer, ForeignKey('loans.loan_id'), nullable=False)
    refinance_date = Column(Date, nullable=False)
    original_balance = Column(Numeric(14, 2), nullable=False)
    new_amount = Column(Numeric(14, 2), nullable=False)
    original_rate = Column(Numeric(6, 4))
    new_rate = Column(Numeric(6, 4))
    cash_out_amount = Column(Numeric(14, 2))
    closing_costs = Column(Numeric(14, 2))


# ============================================================================
# Compliance (6 tables)
# ============================================================================

class KycDocument(Base, AuditMixin):
    """KYC (Know Your Customer) documents."""
    __tablename__ = 'kyc_documents'

    kyc_id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=False)
    document_type = Column(String(50), nullable=False)  # PASSPORT, DRIVERS_LICENSE, SSN_CARD
    document_number = Column(String(100))
    issuing_country = Column(String(3))
    issuing_state = Column(String(50))
    issue_date = Column(Date)
    expiry_date = Column(Date)
    verified = Column(Boolean, default=False)
    verified_date = Column(DateTime)
    verified_by = Column(Integer)
    verification_method = Column(String(50))
    document_image_url = Column(String(500))
    risk_score = Column(Integer)


class AmlCheck(Base, TimestampMixin):
    """AML (Anti-Money Laundering) checks."""
    __tablename__ = 'aml_checks'

    check_id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=False)
    check_type = Column(String(50), nullable=False)
    check_date = Column(DateTime, nullable=False)
    result = Column(String(20), nullable=False)  # PASS, REVIEW, FAIL
    risk_level = Column(String(20))
    match_details = Column(Text)
    reviewed_by = Column(Integer)
    reviewed_date = Column(DateTime)
    notes = Column(Text)


class SanctionsScreening(Base, TimestampMixin):
    """Sanctions screening results."""
    __tablename__ = 'sanctions_screening'

    screening_id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer)
    transaction_id = Column(Integer)
    screening_date = Column(DateTime, nullable=False)
    screening_type = Column(String(50), nullable=False)  # OFAC, EU, UN
    result = Column(String(20), nullable=False)
    match_score = Column(Integer)
    matched_name = Column(String(200))
    matched_list = Column(String(100))
    cleared = Column(Boolean, default=False)
    cleared_by = Column(Integer)
    cleared_date = Column(DateTime)


class SuspiciousActivityReport(Base, AuditMixin):
    """Suspicious Activity Reports (SARs)."""
    __tablename__ = 'suspicious_activity_reports'

    sar_id = Column(Integer, primary_key=True, autoincrement=True)
    reference_number = Column(String(50), nullable=False, unique=True)
    customer_id = Column(Integer)
    account_id = Column(Integer)
    activity_type = Column(String(100), nullable=False)
    activity_start_date = Column(Date)
    activity_end_date = Column(Date)
    amount_involved = Column(Numeric(14, 2))
    description = Column(Text, nullable=False)
    filed_date = Column(Date, nullable=False)
    filer_id = Column(Integer)
    submission_date = Column(Date)
    confirmation_number = Column(String(50))
    status = Column(String(20), nullable=False)


class ComplianceCase(Base, AuditMixin):
    """Compliance investigation cases."""
    __tablename__ = 'compliance_cases'

    case_id = Column(Integer, primary_key=True, autoincrement=True)
    case_number = Column(String(20), nullable=False, unique=True)
    case_type = Column(String(50), nullable=False)
    priority = Column(String(20))
    customer_id = Column(Integer)
    account_id = Column(Integer)
    description = Column(Text)
    opened_date = Column(DateTime, nullable=False)
    due_date = Column(Date)
    closed_date = Column(DateTime)
    assigned_to = Column(Integer)
    status = Column(String(20), nullable=False)
    resolution = Column(Text)
    escalated = Column(Boolean, default=False)


class RegulatoryReport(Base, TimestampMixin):
    """Regulatory reporting."""
    __tablename__ = 'regulatory_reports'

    report_id = Column(Integer, primary_key=True, autoincrement=True)
    report_type = Column(String(50), nullable=False)  # CTR, CMIR, FBAR
    reporting_period_start = Column(Date)
    reporting_period_end = Column(Date)
    due_date = Column(Date, nullable=False)
    submission_date = Column(Date)
    confirmation_number = Column(String(50))
    status = Column(String(20), nullable=False)
    prepared_by = Column(Integer)
    reviewed_by = Column(Integer)
    file_path = Column(String(500))


# ============================================================================
# Users (5 tables)
# ============================================================================

class BankUser(Base, AuditMixin):
    """Bank-specific user accounts."""
    __tablename__ = 'bank_users'

    user_id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=False)
    username = Column(String(50), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    phone = Column(String(20))
    mfa_enabled = Column(Boolean, default=False)
    mfa_method = Column(String(20))
    last_login = Column(DateTime)
    failed_login_count = Column(Integer, default=0)
    locked_until = Column(DateTime)
    password_changed_at = Column(DateTime)
    must_change_password = Column(Boolean, default=False)
    status = Column(String(20), nullable=False)


class BankUserSession(Base):
    """Bank user sessions."""
    __tablename__ = 'bank_user_sessions'

    session_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('bank_users.user_id'), nullable=False)
    session_token = Column(String(255), nullable=False, unique=True)
    ip_address = Column(String(45))
    user_agent = Column(String(500))
    device_fingerprint = Column(String(255))
    started_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    last_activity = Column(DateTime)
    is_active = Column(Boolean, default=True)


class BankLoginHistory(Base):
    """Bank login history."""
    __tablename__ = 'bank_login_history'

    history_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('bank_users.user_id'), nullable=False)
    login_time = Column(DateTime, nullable=False)
    ip_address = Column(String(45))
    user_agent = Column(String(500))
    device_type = Column(String(20))
    location = Column(String(200))
    success = Column(Boolean, nullable=False)
    failure_reason = Column(String(100))
    mfa_used = Column(Boolean, default=False)


class SecurityQuestion(Base, TimestampMixin):
    """Security questions for account recovery."""
    __tablename__ = 'security_questions'

    question_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('bank_users.user_id'), nullable=False)
    question = Column(String(255), nullable=False)
    answer_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)


class TrustedDevice(Base, AuditMixin):
    """Trusted devices for banking."""
    __tablename__ = 'trusted_devices'

    device_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('bank_users.user_id'), nullable=False)
    device_name = Column(String(100))
    device_fingerprint = Column(String(255), nullable=False)
    device_type = Column(String(20))
    operating_system = Column(String(50))
    browser = Column(String(50))
    last_used = Column(DateTime)
    trusted_until = Column(DateTime)
    is_revoked = Column(Boolean, default=False)


# Export all models
__all__ = [
    # Accounts
    'AccountType', 'Account', 'AccountHolder', 'JointAccount', 'SavingsAccount',
    'CheckingAccount', 'MoneyMarketAccount', 'CertificateOfDeposit', 'AccountBeneficiary',
    'AccountStatement', 'AccountAlert', 'AccountLimit',
    # Transactions
    'TransactionType', 'BankTransaction', 'Transfer', 'StandingOrder', 'ScheduledPayment',
    'WireTransfer', 'AchTransfer', 'CheckDeposit', 'AtmTransaction', 'PosTransaction',
    'TransactionDispute', 'TransactionCategory', 'TransactionTag', 'RecurringTransaction',
    'TransactionFee',
    # Cards
    'CreditCard', 'DebitCard', 'CardTransaction', 'CardLimit', 'CardReward',
    'CardRewardRedemption', 'CardStatement', 'VirtualCard', 'CardControl', 'CardDispute',
    # Loans
    'LoanType', 'Loan', 'LoanApplication', 'LoanPayment', 'LoanSchedule', 'Collateral',
    'Guarantor', 'LoanDocument', 'LoanOfficer', 'LoanStatusHistory', 'LoanFee', 'LoanRefinancing',
    # Compliance
    'KycDocument', 'AmlCheck', 'SanctionsScreening', 'SuspiciousActivityReport',
    'ComplianceCase', 'RegulatoryReport',
    # Users
    'BankUser', 'BankUserSession', 'BankLoginHistory', 'SecurityQuestion', 'TrustedDevice',
]
