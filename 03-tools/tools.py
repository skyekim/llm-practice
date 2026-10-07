"""Exercise 3, step 2: narrow, read-only query functions for the model to call.

Every function returns plain lists and dicts that json.dumps can handle.
"""
import json
import os

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from setup_db import normalize_skill

load_dotenv()

VALID_STATUSES = ("saved", "applied", "interviewing", "offer", "rejected")


def connect():
    # dict_row returns each row as {"column": value} instead of a tuple.
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


def search_postings(skill=None, min_salary=None, max_years=None, ai_company=None):
    """Find postings matching every filter given. All filters are optional.

    skill:      exact match after normalizing ("Postgres" finds "postgresql")
    min_salary: the top of the posted range reaches at least this much;
                postings without a salary are excluded
    max_years:  requires at most this many years; postings that don't
                state a requirement are included
    ai_company: True or False
    """
    # The SQL fragments are fixed strings written here; only the values,
    # sent separately as params, come from the caller.
    conditions = []
    params = []

    if skill is not None:
        conditions.append(
            "EXISTS (SELECT 1 FROM posting_skills s WHERE s.posting_id = p.id AND s.skill = %s)"
        )
        params.append(normalize_skill(skill))
    if min_salary is not None:
        conditions.append("p.salary_max >= %s")
        params.append(min_salary)
    if max_years is not None:
        conditions.append("(p.min_years IS NULL OR p.min_years <= %s)")
        params.append(max_years)
    if ai_company is not None:
        conditions.append("c.ai_company = %s")
        params.append(ai_company)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    sql = f"""
        SELECT p.id, c.name AS company, p.title, p.salary_min, p.salary_max
        FROM postings p JOIN companies c ON c.id = p.company_id
        {where}
        ORDER BY p.salary_max DESC NULLS LAST, p.id
    """
    with connect() as conn:
        return conn.execute(sql, params).fetchall()


def get_posting(posting_id):
    """Return one posting's details, skills, and latest application, without raw_text."""
    with connect() as conn:
        posting = conn.execute(
            """SELECT p.id, p.slug, c.name AS company, c.ai_company, p.title, p.location,
                      p.min_years, p.salary_min, p.salary_max
               FROM postings p JOIN companies c ON c.id = p.company_id
               WHERE p.id = %s""",
            (posting_id,),
        ).fetchone()
        if posting is None:
            return {"error": f"No posting with id {posting_id}"}

        skills = conn.execute(
            "SELECT skill FROM posting_skills WHERE posting_id = %s ORDER BY skill",
            (posting_id,),
        ).fetchall()
        posting["skills"] = [row["skill"] for row in skills]

        application = conn.execute(
            """SELECT status, applied_date, notes FROM applications
               WHERE posting_id = %s ORDER BY id DESC LIMIT 1""",
            (posting_id,),
        ).fetchone()
        if application and application["applied_date"]:
            application["applied_date"] = application["applied_date"].isoformat()
        posting["application"] = application

    return posting


def get_applications(status=None):
    """List applications, newest first, optionally filtered by status."""
    if status is not None and status not in VALID_STATUSES:
        return {"error": f"Unknown status {status!r}. Use one of: {', '.join(VALID_STATUSES)}"}

    sql = """
        SELECT a.id, a.posting_id, c.name AS company, p.title,
               a.status, a.applied_date, a.notes
        FROM applications a
        JOIN postings p ON p.id = a.posting_id
        JOIN companies c ON c.id = p.company_id
    """
    params = []
    if status is not None:
        sql += " WHERE a.status = %s"
        params.append(status)
    sql += " ORDER BY a.applied_date DESC NULLS LAST, a.id"

    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    for row in rows:
        if row["applied_date"]:
            row["applied_date"] = row["applied_date"].isoformat()
    return rows


# Tool definitions sent to the model. The descriptions are the only thing the
# model knows about these functions, so they spell out how the data is stored.
TOOLS = [
    {
        "name": "search_postings",
        "description": (
            "Search the user's saved job postings by optional filters; all filters "
            "given must match. Call with no filters to list every posting. "
            "Returns each match's id, company, title, salary_min, and salary_max "
            "(null when the posting lists no salary). Use get_posting with an id "
            "for location, years of experience, skills, and application status."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "skill": {
                    "type": "string",
                    "description": (
                        "One skill, matched exactly. Skills are stored in lowercase "
                        "with canonical names, e.g. 'python', 'kubernetes', "
                        "'postgresql' (not 'postgres'), 'go' (not 'golang'). "
                        "Partial matches don't work: 'pipelines' won't find "
                        "'data pipelines'. To search for several skills, call "
                        "once per skill and combine the results."
                    ),
                },
                "min_salary": {
                    "type": "integer",
                    "description": (
                        "Annual USD, e.g. 200000. Matches postings whose salary "
                        "range reaches at least this amount (salary_max >= "
                        "min_salary). Excludes postings with no listed salary."
                    ),
                },
                "max_years": {
                    "type": "integer",
                    "description": (
                        "Matches postings requiring at most this many years of "
                        "experience. Postings that don't state a requirement are "
                        "included."
                    ),
                },
                "ai_company": {
                    "type": "boolean",
                    "description": "true for companies whose product is AI-focused, false for the rest.",
                },
            },
        },
    },
    {
        "name": "get_posting",
        "description": (
            "Get full details for one job posting by id: company, title, location, "
            "minimum years of experience, salary range, its full skill list, and "
            "the user's latest application (null if they haven't saved or applied). "
            "Get ids from search_postings or get_applications."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "posting_id": {"type": "integer", "description": "The posting's id."},
            },
            "required": ["posting_id"],
        },
    },
    {
        "name": "get_applications",
        "description": (
            "List the user's job applications, newest first, with company, title, "
            "status, applied_date (null for saved postings), notes, and posting_id. "
            "Use this for questions about where the user has applied or what stage "
            "they're at."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": list(VALID_STATUSES),
                    "description": "Only return applications with this status. Omit for all.",
                },
            },
        },
    },
]


if __name__ == "__main__":
    # json.dumps fails loudly if anything isn't JSON-serializable.
    def show(label, result):
        print(f"--- {label}")
        print(json.dumps(result, indent=2))

    show("search_postings(skill='Postgres')", search_postings(skill="Postgres"))
    show("search_postings(min_salary=250000, max_years=2, ai_company=True)",
         search_postings(min_salary=250000, max_years=2, ai_company=True))
    show("get_posting(1)", get_posting(1))
    show("get_posting(999)", get_posting(999))
    show("get_applications()", get_applications())
    show("get_applications('pending')", get_applications("pending"))
    show("search_postings(skill=\"x' OR 1=1 --\")", search_postings(skill="x' OR 1=1 --"))
