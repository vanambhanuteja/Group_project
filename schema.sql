PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY,
    name VARCHAR(60) NOT NULL UNIQUE,
    color VARCHAR(12) NOT NULL DEFAULT '#8778e8'
);

CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY,
    title VARCHAR(120) NOT NULL,
    amount REAL NOT NULL CHECK (amount > 0),
    category_id INTEGER NOT NULL REFERENCES categories(id),
    spent_on DATE NOT NULL,
    description VARCHAR(500) NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS budgets (
    id INTEGER PRIMARY KEY,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    amount REAL NOT NULL CHECK (amount > 0),
    month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    year INTEGER NOT NULL CHECK (year BETWEEN 2000 AND 2100),
    UNIQUE (category_id, month, year)
);

CREATE INDEX IF NOT EXISTS ix_expenses_spent_on ON expenses(spent_on);
CREATE INDEX IF NOT EXISTS ix_expenses_category_id ON expenses(category_id);
CREATE INDEX IF NOT EXISTS ix_budgets_category_month_year ON budgets(category_id, month, year);
