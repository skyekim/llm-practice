"""Exercise 3, step 1: build the job search database from exercise 2's results.

Drops and recreates every table, so rerunning it resets the database.
"""
import json
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

EXTRACTION_DIR = Path(__file__).parent.parent / "02-extraction"
RESULTS_FILE = EXTRACTION_DIR / "results_b.json"
POSTINGS_DIR = EXTRACTION_DIR / "postings"

# Children before parents isn't needed with CASCADE, but it keeps the intent clear.
DROP = "DROP TABLE IF EXISTS applications, posting_skills, postings, companies CASCADE"

SCHEMA = """
CREATE TABLE companies (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    ai_company BOOLEAN NOT NULL
);

CREATE TABLE postings (
    id         SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    slug       TEXT NOT NULL UNIQUE,
    title      TEXT NOT NULL,
    location   TEXT,
    min_years  INTEGER,
    salary_min INTEGER,
    salary_max INTEGER,
    raw_text   TEXT NOT NULL
);

CREATE TABLE posting_skills (
    posting_id INTEGER NOT NULL REFERENCES postings(id) ON DELETE CASCADE,
    skill      TEXT NOT NULL,
    PRIMARY KEY (posting_id, skill)
);

CREATE TABLE applications (
    id           SERIAL PRIMARY KEY,
    posting_id   INTEGER NOT NULL REFERENCES postings(id) ON DELETE CASCADE,
    status       TEXT NOT NULL
                 CHECK (status IN ('saved', 'applied', 'interviewing', 'offer', 'rejected')),
    applied_date DATE,
    notes        TEXT
);
"""

# Spellings that mean the same skill, after lowercasing.
SKILL_ALIASES = {
    "postgres": "postgresql",
    "golang": "go",
    "ml ops": "mlops",
    "llm": "llms",
    "full stack development": "full-stack development",
}

# Test data: (slug, status, applied_date, notes)
APPLICATIONS = [
    ("giga", "applied", "2026-10-01", "Applied through the careers page"),
    ("bevel", "interviewing", "2026-09-24", "Recruiter screen done, technical next"),
    ("guac", "saved", None, "Strong match on Python, FastAPI, and RAG"),
]


def normalize_skill(skill: str) -> str:
    key = skill.strip().lower()
    return SKILL_ALIASES.get(key, key)


def main():
    results = json.loads(RESULTS_FILE.read_text())

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute(DROP)
        conn.execute(SCHEMA)

        posting_ids = {}
        for slug, p in results.items():
            if p is None:
                print(f"skipping {slug}: extraction failed")
                continue

            company_id = conn.execute(
                """INSERT INTO companies (name, ai_company) VALUES (%s, %s)
                   ON CONFLICT (name) DO UPDATE SET ai_company = EXCLUDED.ai_company
                   RETURNING id""",
                (p["company"], p["ai_company"]),
            ).fetchone()[0]

            raw_text = (POSTINGS_DIR / f"{slug}.txt").read_text()
            posting_id = conn.execute(
                """INSERT INTO postings (company_id, slug, title, location, min_years,
                                         salary_min, salary_max, raw_text)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (company_id, slug, p["title"], p["location"], p["min_years"],
                 p["salary_min"], p["salary_max"], raw_text),
            ).fetchone()[0]
            posting_ids[slug] = posting_id

            # Two spellings can normalize to the same skill; the primary key dedupes them.
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO posting_skills VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    [(posting_id, normalize_skill(s)) for s in p["skills"]],
                )

        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO applications (posting_id, status, applied_date, notes)
                   VALUES (%s, %s, %s, %s)""",
                [(posting_ids[slug], status, date, notes)
                 for slug, status, date, notes in APPLICATIONS],
            )

        for table in ("companies", "postings", "posting_skills", "applications"):
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"{table}: {count} rows")


if __name__ == "__main__":
    main()
