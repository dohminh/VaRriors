from __future__ import annotations
from pydantic import BaseModel, Field, model_validator
from uuid import UUID, uuid4
from typing import List, Optional
from enum import Enum
from decimal import Decimal
from datetime import date, datetime
from . import db
from flask_login import UserMixin
from sqlalchemy.sql import func


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True)
    password = db.Column(db.String(150))
    first_name = db.Column(db.String(150))
    cashflows = db.relationship('Cashflow', backref='user')
    budgets = db.relationship('Budget', backref='user')
    saving_goals = db.relationship('SavingGoal', backref='user')


class Cashflow(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Numeric(precision=10, scale=2), nullable=False)
    kind = db.Column(db.String(20), nullable=False)
    category = db.Column(db.String(50), nullable=True)
    date = db.Column(db.Date, default=datetime.utcnow())


# ───────────────────────────────────────────────
#  Enumerations
# ───────────────────────────────────────────────


class Category(str, Enum):
    ESSENTIAL_SPENDING = "Essential Spending"
    SHOPPING_ENTERTAINMENT = "Shopping & Entertainment"
    EDUCATION = "Education"
    HEALTH = "Health"
    INSURANCE = "Insurance"
    INVESTMENT = "Investment"
    OTHER = "Other"


class IncomeCategory(str, Enum):
    FULL_TIME = "Full‑time Income"
    PART_TIME = "Part‑time Income"
    FREELANCE = "Freelance Income"
    BONUS = "Bonus"


class TransactionKind(str, Enum):
    INCOME = "Income"
    EXPENSE = "Expense"
    SAVINGS = "Savings"


class FinancialCondition(str, Enum):
    STABLE = "Stable"
    VULNERABLE = "Vulnerable"
    AT_RISK = "At‑Risk"


class BadgeName(str, Enum):
    STREAK_7 = "🔥 7‑day streak"
    STREAK_30 = "🏅 30‑day streak"
    STREAK_60 = "🏆 60‑day streak"

# ───────────────────────────────────────────────
#  Core entities
# ───────────────────────────────────────────────


class Transaction(BaseModel):
    """Một giao dịch đơn lẻ –  `amount` luôn **dương**.
    Nếu `kind == INCOME` có thể chỉ định `income_category` để phân loại.
    """

    id: UUID = Field(default_factory=uuid4)
    amount: Decimal = Field(..., gt=0)
    kind: TransactionKind
    category: Category
    txn_date: date
    income_category: Optional[IncomeCategory] = None

    @property
    def signed_amount(self) -> Decimal:
        return self.amount if self.kind is TransactionKind.INCOME else -self.amount

    # Validators ---------------------------------------------------------
    @model_validator(mode="after")
    def _check_fields(cls, m: "Transaction"):
        if m.txn_date > date.today():
            raise ValueError("Transaction date cannot be in the future.")
        if m.kind is TransactionKind.INCOME and m.income_category is None:
            raise ValueError(
                "income_category is required for Income transactions.")
        if m.kind is TransactionKind.EXPENSE and m.income_category is not None:
            raise ValueError(
                "income_category must be None for Expense transactions.")
        return m

    model_config = {"frozen": True, "extra": "forbid"}

# ───────────────────────────────────────────────
#  Budgeting
# ───────────────────────────────────────────────


class BudgetRule(BaseModel):
    category: Category
    monthly_limit: Decimal = Field(..., gt=0)

    model_config = {"frozen": True, "extra": "forbid"}


class BudgetResult(BaseModel):
    category: Category
    actual: Decimal
    planned: Decimal
    pct_diff: float
    overspent: bool

    model_config = {"frozen": True, "extra": "forbid"}


class Budget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    category = db.Column(db.String(150))
    month = db.Column(db.String(7))  # Format: YYYY-MM
    planned_amount = db.Column(db.Float)
    created_at = db.Column(db.DateTime(timezone=True), default=func.now())
    
    def calculate_usage(self, actual_spending):
        """Calculate budget usage percentage"""
        if self.planned_amount == 0:
            return 0
        return (actual_spending / self.planned_amount) * 100
    
    def get_remaining(self, actual_spending):
        """Calculate remaining budget"""
        return self.planned_amount - actual_spending


class SavingGoal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    name = db.Column(db.String(150))
    total_amount = db.Column(db.Float)
    start_date = db.Column(db.Date)
    target_date = db.Column(db.Date)
    past_savings = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime(timezone=True), default=func.now())
    
    def calculate_monthly_saving(self):
        """Calculate required monthly saving"""
        if not self.start_date or not self.target_date:
            return 0
            
        # Calculate months between start and target date
        months = (
            (self.target_date.year - self.start_date.year) * 12 
            + self.target_date.month - self.start_date.month
        )
        
        if months <= 0:
            return 0
            
        return (self.total_amount - self.past_savings) / months
    
    def calculate_progress(self, current_savings):
        """Calculate saving progress percentage"""
        if self.total_amount == 0:
            return 0
        return (current_savings / self.total_amount) * 100
    
    def is_on_track(self, current_monthly_saving):
        """Check if saving goal is on track"""
        required = self.calculate_monthly_saving()
        return current_monthly_saving >= required
    
    def get_saving_gap(self, current_monthly_saving):
        """Calculate gap between required and current monthly saving"""
        required = self.calculate_monthly_saving()
        return required - current_monthly_saving

# ───────────────────────────────────────────────
#  Stress‑testing
# ───────────────────────────────────────────────


class StressScenario(BaseModel):
    name: str
    income_shock_pct: float = Field(0.0, ge=0.0, le=1.0)
    expense_spike_pct: float = Field(0.0, ge=0.0, le=1.0)
    months: int = Field(6, ge=1, le=12)

    model_config = {"frozen": True, "extra": "forbid"}


class StressResult(BaseModel):
    projected_cashflow: List[Decimal]
    resilience_score: int = Field(..., ge=0, le=100)
    condition: FinancialCondition

    model_config = {"frozen": True, "extra": "forbid"}

# ───────────────────────────────────────────────
#  Streak & Badge
# ───────────────────────────────────────────────


class Badge(BaseModel):
    name: BadgeName
    awarded_on: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"frozen": True, "extra": "forbid"}


class StreakInfo(BaseModel):
    current: int = Field(0, ge=0)
    longest: int = Field(0, ge=0)
    last_activity: Optional[date] = None
    new_badges: List[Badge] = Field(default_factory=list)

    model_config = {"frozen": True, "extra": "forbid"}

# ───────────────────────────────────────────────
#  Cash‑flow summary
# ───────────────────────────────────────────────


class CashflowSummary(BaseModel):
    month: str            # "YYYY‑MM"
    income: Decimal
    expense: Decimal
    net: Decimal

    model_config = {"frozen": True, "extra": "forbid"}

# ───────────────────────────────────────────────
#  Helper
# ───────────────────────────────────────────────


def month_str(d: date | datetime) -> str:
    return d.strftime("%Y-%m")

# ───────────────────────────────────────────────
#  Export
# ───────────────────────────────────────────────


__all__ = [
    "User",
    "Cashflow",
    "Category",
    "IncomeCategory",
    "TransactionKind",
    "FinancialCondition",
    "BadgeName",
    "Transaction",
    "BudgetRule",
    "BudgetResult",
    "StressScenario",
    "StressResult",
    "StreakInfo",
    "Badge",
    "CashflowSummary",
    "month_str",
]
