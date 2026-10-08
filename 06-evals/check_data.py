"""Exercise 6, step 2: print the data the expected answers in cases.json rely on,
so they can be checked against the database instead of memory."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "05-agent"))
from db import connect  # noqa: E402

QUERIES = {
    "applications": """
        SELECT c.name, a.status, a.applied_date
        FROM applications a
        JOIN postings p ON p.id = a.posting_id
        JOIN companies c ON c.id = p.company_id
        ORDER BY c.name
    """,
    "skills": """
        SELECT s.skill, string_agg(c.name, ', ' ORDER BY c.name) AS companies
        FROM posting_skills s
        JOIN postings p ON p.id = s.posting_id
        JOIN companies c ON c.id = p.company_id
        WHERE s.skill IN ('kubernetes', 'python', 'postgresql', 'go')
        GROUP BY s.skill
        ORDER BY s.skill
    """,
    "years and salary": """
        SELECT c.name, p.min_years, p.salary_min, p.salary_max
        FROM postings p
        JOIN companies c ON c.id = p.company_id
        ORDER BY c.name
    """,
}

with connect() as conn:
    for label, sql in QUERIES.items():
        print(f"--- {label}")
        for row in conn.execute(sql).fetchall():
            print(row)
