from __future__ import annotations

from calendar import month_name
from datetime import date
from pathlib import Path
from typing import Generator

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Date, Float, ForeignKey, Integer, String, UniqueConstraint, create_engine, func, or_, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


ROOT = Path(__file__).resolve().parent
engine = create_engine(f"sqlite:///{ROOT / 'expenses.db'}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    color: Mapped[str] = mapped_column(String(12), default="#8778e8")
    expenses: Mapped[list[Expense]] = relationship(back_populates="category")
    budgets: Mapped[list[Budget]] = relationship(back_populates="category")


class Expense(Base):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(120), index=True)
    amount: Mapped[float] = mapped_column(Float)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    spent_on: Mapped[date] = mapped_column(Date, index=True)
    description: Mapped[str] = mapped_column(String(500), default="")
    category: Mapped[Category] = relationship(back_populates="expenses")


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("category_id", "month", "year", name="uq_budget_category_month_year"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    amount: Mapped[float] = mapped_column(Float)
    month: Mapped[int] = mapped_column(Integer)
    year: Mapped[int] = mapped_column(Integer)
    category: Mapped[Category] = relationship(back_populates="budgets")


class ExpenseInput(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    amount: float = Field(gt=0, le=100000000)
    category_id: int = Field(gt=0)
    spent_on: date
    description: str = Field(default="", max_length=500)
    confirm_over_budget: bool = False

    @field_validator("title")
    @classmethod
    def title_has_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Title cannot be blank.")
        return value

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str) -> str:
        return value.strip()


class BudgetInput(BaseModel):
    category_id: int = Field(gt=0)
    amount: float = Field(gt=0, le=100000000)
    month: int = Field(ge=1, le=12)
    year: int = Field(ge=2000, le=2100)


class CategoryInput(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    color: str = Field(default="#8778e8", pattern=r"^#[0-9a-fA-F]{6}$")

    @field_validator("name")
    @classmethod
    def name_has_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Category name cannot be blank.")
        return value


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def expense_json(row: Expense) -> dict:
    return {"id": row.id, "title": row.title, "amount": row.amount, "category_id": row.category_id,
            "category": row.category.name, "category_color": row.category.color,
            "spent_on": row.spent_on.isoformat(), "description": row.description or ""}


def budget_json(row: Budget, spent: float = 0) -> dict:
    return {"id": row.id, "category_id": row.category_id, "category": row.category.name,
            "color": row.category.color, "amount": row.amount, "spent": spent,
            "month": row.month, "year": row.year}


class BudgetGuard:
    @staticmethod
    def check(db: Session, category_id: int, amount: float, spent_on: date, exclude_id: int | None = None) -> dict | None:
        budget = db.scalar(select(Budget).where(Budget.category_id == category_id,
                                                Budget.month == spent_on.month, Budget.year == spent_on.year))
        if not budget:
            return None
        query = select(func.coalesce(func.sum(Expense.amount), 0)).where(
            Expense.category_id == category_id, func.strftime("%m", Expense.spent_on) == f"{spent_on.month:02d}",
            func.strftime("%Y", Expense.spent_on) == str(spent_on.year))
        if exclude_id is not None:
            query = query.where(Expense.id != exclude_id)
        current = float(db.scalar(query) or 0)
        projected = current + amount
        return {"category": budget.category.name, "limit": budget.amount, "spent": current,
                "projected": projected, "remaining": budget.amount - projected,
                "over": projected > budget.amount}


class ExpenseService:
    @staticmethod
    def save(db: Session, data: ExpenseInput, expense_id: int | None = None) -> Expense:
        category = db.get(Category, data.category_id)
        if not category:
            raise HTTPException(400, "Choose a valid category.")
        guard = BudgetGuard.check(db, data.category_id, data.amount, data.spent_on, expense_id)
        if guard and guard["over"] and not data.confirm_over_budget:
            raise HTTPException(409, {"message": "This expense would exceed the category budget.", "budget": guard})
        row = db.get(Expense, expense_id) if expense_id is not None else Expense()
        if expense_id is not None and row is None:
            raise HTTPException(404, "Expense not found.")
        row.title, row.amount, row.category_id = data.title.strip(), data.amount, data.category_id
        row.spent_on, row.description = data.spent_on, data.description.strip()
        db.add(row)
        db.commit()
        db.refresh(row)
        return row


class ReportEngine:
    @staticmethod
    def summary(db: Session, month: int, year: int) -> dict:
        rows = list(db.scalars(select(Expense).where(func.strftime("%m", Expense.spent_on) == f"{month:02d}",
                                                               func.strftime("%Y", Expense.spent_on) == str(year))))
        budgets = list(db.scalars(select(Budget).where(Budget.month == month, Budget.year == year)))
        total = sum(x.amount for x in rows)
        budget_total = sum(x.amount for x in budgets)
        by_category: dict[int, dict] = {}
        for item in rows:
            entry = by_category.setdefault(item.category_id, {"category_id": item.category_id,
                "category": item.category.name, "color": item.category.color, "spent": 0.0, "budget": 0.0})
            entry["spent"] += item.amount
        for item in budgets:
            entry = by_category.setdefault(item.category_id, {"category_id": item.category_id,
                "category": item.category.name, "color": item.category.color, "spent": 0.0, "budget": 0.0})
            entry["budget"] = item.amount
        return {"month": month, "year": year, "month_name": month_name[month], "total": total,
                "budget_total": budget_total, "remaining": budget_total - total,
                "count": len(rows), "categories": sorted(by_category.values(), key=lambda x: x["spent"], reverse=True),
                "recent": [expense_json(x) for x in sorted(rows, key=lambda x: x.spent_on, reverse=True)[:6]]}

    @staticmethod
    def yearly(db: Session, end_year: int) -> list[dict]:
        start_year = end_year - 4
        totals = db.execute(
            select(func.strftime("%Y", Expense.spent_on), func.sum(Expense.amount))
            .where(func.strftime("%Y", Expense.spent_on).between(str(start_year), str(end_year)))
            .group_by(func.strftime("%Y", Expense.spent_on))
        ).all()
        by_year = {int(y): float(total or 0) for y, total in totals if y}
        return [{"year": year, "total": by_year.get(year, 0.0)} for year in range(start_year, end_year + 1)]


Base.metadata.create_all(engine)
with SessionLocal() as _db:
    if not _db.scalar(select(Category.id).limit(1)):
        _db.add_all([Category(name=n, color=c) for n, c in [
            ("Food & drink", "#f2a675"), ("Transport", "#83b9f3"), ("Shopping", "#c18af4"),
            ("Bills", "#f07887"), ("Health", "#71c8ab"), ("Entertainment", "#f1c56c"),
            ("Home", "#8ba2e8"), ("Other", "#a5a5b1")]])
        _db.commit()

app = FastAPI(title="Moneymap · Expense Manager", version="1.0.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def home():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/categories")
def categories(db: Session = Depends(get_db)):
    return [{"id": x.id, "name": x.name, "color": x.color} for x in db.scalars(select(Category).order_by(Category.name))]


@app.post("/api/categories", status_code=201)
def add_category(data: CategoryInput, db: Session = Depends(get_db)):
    name = data.name.strip()
    if db.scalar(select(Category).where(func.lower(Category.name) == name.lower())):
        raise HTTPException(409, "That category already exists.")
    row = Category(name=name, color=data.color)
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "name": row.name, "color": row.color}


@app.get("/api/expenses")
def expenses(q: str = "", category_id: int | None = None, month: int | None = None, year: int | None = None,
             start: date | None = None, end: date | None = None, db: Session = Depends(get_db)):
    query = select(Expense).join(Category)
    if q.strip(): query = query.where(or_(Expense.title.ilike(f"%{q.strip()}%"), Expense.description.ilike(f"%{q.strip()}%"), Category.name.ilike(f"%{q.strip()}%")))
    if category_id: query = query.where(Expense.category_id == category_id)
    if month: query = query.where(func.strftime("%m", Expense.spent_on) == f"{month:02d}")
    if year: query = query.where(func.strftime("%Y", Expense.spent_on) == str(year))
    if start: query = query.where(Expense.spent_on >= start)
    if end: query = query.where(Expense.spent_on <= end)
    return [expense_json(x) for x in db.scalars(query.order_by(Expense.spent_on.desc(), Expense.id.desc()))]


@app.post("/api/expenses", status_code=201)
def create_expense(data: ExpenseInput, db: Session = Depends(get_db)):
    return expense_json(ExpenseService.save(db, data))


@app.get("/api/expenses/{expense_id}")
def get_expense(expense_id: int, db: Session = Depends(get_db)):
    row = db.get(Expense, expense_id)
    if not row: raise HTTPException(404, "Expense not found.")
    return expense_json(row)


@app.put("/api/expenses/{expense_id}")
def update_expense(expense_id: int, data: ExpenseInput, db: Session = Depends(get_db)):
    return expense_json(ExpenseService.save(db, data, expense_id))


@app.delete("/api/expenses/{expense_id}", status_code=204)
def delete_expense(expense_id: int, db: Session = Depends(get_db)):
    row = db.get(Expense, expense_id)
    if not row: raise HTTPException(404, "Expense not found.")
    db.delete(row); db.commit()


@app.get("/api/budgets")
def budgets(month: int | None = None, year: int | None = None, db: Session = Depends(get_db)):
    today = date.today(); month, year = month or today.month, year or today.year
    rows = db.scalars(select(Budget).where(Budget.month == month, Budget.year == year).order_by(Budget.id))
    return [budget_json(x, float(db.scalar(select(func.coalesce(func.sum(Expense.amount), 0)).where(
        Expense.category_id == x.category_id, func.strftime("%m", Expense.spent_on) == f"{month:02d}",
        func.strftime("%Y", Expense.spent_on) == str(year))) or 0)) for x in rows]


@app.post("/api/budgets", status_code=201)
def save_budget(data: BudgetInput, db: Session = Depends(get_db)):
    if not db.get(Category, data.category_id): raise HTTPException(400, "Choose a valid category.")
    row = db.scalar(select(Budget).where(Budget.category_id == data.category_id,
                                         Budget.month == data.month, Budget.year == data.year))
    if row is None: row = Budget(category_id=data.category_id, month=data.month, year=data.year)
    row.amount = data.amount; db.add(row); db.commit(); db.refresh(row)
    spent = float(db.scalar(select(func.coalesce(func.sum(Expense.amount), 0)).where(
        Expense.category_id == row.category_id, func.strftime("%m", Expense.spent_on) == f"{row.month:02d}",
        func.strftime("%Y", Expense.spent_on) == str(row.year))) or 0)
    return budget_json(row, spent)


@app.delete("/api/budgets/{budget_id}", status_code=204)
def delete_budget(budget_id: int, db: Session = Depends(get_db)):
    row = db.get(Budget, budget_id)
    if not row: raise HTTPException(404, "Budget not found.")
    db.delete(row); db.commit()


@app.get("/api/reports/summary")
def report_summary(month: int | None = Query(default=None, ge=1, le=12),
                   year: int | None = Query(default=None, ge=2000, le=2100),
                   db: Session = Depends(get_db)):
    today = date.today()
    return ReportEngine.summary(db, month or today.month, year or today.year)


@app.get("/api/reports/monthly")
def monthly_report(year: int = date.today().year, db: Session = Depends(get_db)):
    return [ReportEngine.summary(db, month, year) for month in range(1, 13)]


@app.get("/api/reports/yearly")
def yearly_report(year: int | None = Query(default=None, ge=2000, le=2100),
                  db: Session = Depends(get_db)):
    return ReportEngine.yearly(db, year or date.today().year)
