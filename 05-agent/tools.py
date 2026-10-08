"""Exercise 5, step 1: every tool the agent can call, and their definitions.

Structured search over the database (from exercise 3) and semantic search over
the full posting text (from exercise 4), plus update_application, the one tool
that writes. Every function returns plain lists and dicts that json.dumps can
handle.
"""
import json
from datetime import date
from functools import cache

from db import connect

VALID_STATUSES = ("saved", "applied", "interviewing", "offer", "rejected")

# Spellings that mean the same skill, after lowercasing. Must match the aliases
# 03-tools/setup_db.py used when it stored the skills.
SKILL_ALIASES = {
    "postgres": "postgresql",
    "golang": "go",
    "ml ops": "mlops",
    "llm": "llms",
    "full stack development": "full-stack development",
}

# Must be the same model that embedded the chunks, or the vectors aren't comparable.
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
TOP_K = 10


def normalize_skill(skill: str) -> str:
    key = skill.strip().lower()
    return SKILL_ALIASES.get(key, key)


@cache
def embedder():
    # Imported and loaded on first use, since it takes a few seconds and
    # questions answered from the database alone never need it.
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(EMBEDDING_MODEL_NAME)


def search_postings(skill=None, min_salary=None, max_years=None, ai_company=None, company=None):
    """Find postings matching every filter given. All filters are optional.

    skill:      exact match after normalizing ("Postgres" finds "postgresql")
    min_salary: the top of the posted range reaches at least this much;
                postings without a salary are excluded
    max_years:  requires at most this many years; postings that don't
                state a requirement are included
    ai_company: True or False
    company:    case-insensitive substring of the company name ("open" finds "OpenAI")
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
    if company is not None:
        conditions.append("c.name ILIKE '%%' || %s || '%%'")
        params.append(company.strip())

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


def update_application(posting_id, status=None, applied_date=None, notes=None):
    """Change the posting's latest application, or create one if there is none.

    Only the fields given change. notes are added after any existing notes,
    so nothing the user wrote earlier is lost. The agent asks the user to
    confirm before this runs.
    """
    if status is None and applied_date is None and notes is None:
        return {"error": "Nothing to change: give status, applied_date, or notes"}
    if status is not None and status not in VALID_STATUSES:
        return {"error": f"Unknown status {status!r}. Use one of: {', '.join(VALID_STATUSES)}"}
    if applied_date is not None:
        try:
            applied_date = date.fromisoformat(applied_date)
        except ValueError:
            return {"error": f"applied_date must be YYYY-MM-DD, got {applied_date!r}"}

    with connect() as conn:
        if conn.execute("SELECT 1 FROM postings WHERE id = %s", (posting_id,)).fetchone() is None:
            return {"error": f"No posting with id {posting_id}"}

        # Same row get_posting reports as the posting's application.
        existing = conn.execute(
            "SELECT id FROM applications WHERE posting_id = %s ORDER BY id DESC LIMIT 1",
            (posting_id,),
        ).fetchone()

        if existing is None:
            if status is None:
                return {"error": "This posting has no application yet; give a status to create one"}
            row = conn.execute(
                """INSERT INTO applications (posting_id, status, applied_date, notes)
                   VALUES (%s, %s, %s, %s)
                   RETURNING id, posting_id, status, applied_date, notes""",
                (posting_id, status, applied_date, notes),
            ).fetchone()
            action = "created"
        else:
            # As in search_postings, the SQL fragments are fixed strings; only values come from the caller.
            sets, params = [], []
            if status is not None:
                sets.append("status = %s")
                params.append(status)
            if applied_date is not None:
                sets.append("applied_date = %s")
                params.append(applied_date)
            if notes is not None:
                sets.append("notes = CASE WHEN notes IS NULL OR notes = '' THEN %s "
                            "ELSE notes || E'\\n' || %s END")
                params += [notes, notes]
            row = conn.execute(
                f"""UPDATE applications SET {', '.join(sets)} WHERE id = %s
                    RETURNING id, posting_id, status, applied_date, notes""",
                params + [existing["id"]],
            ).fetchone()
            action = "updated"

    if row["applied_date"]:
        row["applied_date"] = row["applied_date"].isoformat()
    return {"action": action, "application": row}


def search_posting_text(query, posting_id=None):
    """Return the TOP_K chunks of posting text closest in meaning to query.

    posting_id: only search that one posting's text
    """
    embedding = embedder().encode(query)
    # <=> is cosine distance, so 1 - distance is cosine similarity.
    sql = """
        SELECT c.id AS chunk_id, c.posting_id, co.name AS company, p.title,
               1 - (c.embedding <=> %s) AS similarity, c.text
        FROM chunks c
        JOIN postings p ON p.id = c.posting_id
        JOIN companies co ON co.id = p.company_id
    """
    params = [embedding]
    if posting_id is not None:
        sql += " WHERE c.posting_id = %s"
        params.append(posting_id)
    sql += " ORDER BY c.embedding <=> %s LIMIT %s"
    params += [embedding, TOP_K]

    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    if not rows and posting_id is not None:
        return {"error": f"No posting text for posting id {posting_id}"}
    for row in rows:
        row["similarity"] = round(row["similarity"], 3)
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
                "company": {
                    "type": "string",
                    "description": (
                        "Company name, case-insensitive; partial names match "
                        "('open' finds 'OpenAI'). Misspellings won't match: if "
                        "nothing comes back, call with no filters to see every "
                        "company name."
                    ),
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
    {
        "name": "search_posting_text",
        "description": (
            "Semantic search over the full text of the job postings, for anything "
            "the structured fields don't cover: benefits, visa sponsorship, remote "
            "policy, team, responsibilities, culture. Returns the "
            f"{TOP_K} closest excerpts, each with chunk_id, posting_id, company, "
            "title, similarity (higher is closer), and text. Excerpts are ranked by "
            "meaning, so the top ones may still not answer the question; read the "
            "text before relying on it. Cite chunk ids for claims, like [chunk 12]."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "What to look for, phrased like the posting would say it, "
                        "e.g. 'visa sponsorship available' or 'fully remote team'."
                    ),
                },
                "posting_id": {
                    "type": "integer",
                    "description": "Only search this posting's text. Omit to search every posting.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "update_application",
        "description": (
            "Change the user's application for one posting: its status, "
            "applied_date, or notes. Updates the posting's latest application, or "
            "creates one if there is none (status is then required). This changes "
            "the user's data, so only call it when the user says something "
            "changed. The app shows the user the change and asks them y/n before "
            "it runs, so don't ask for confirmation in chat; call it directly. "
            "If they decline, nothing changes: don't retry, just tell them the "
            "change wasn't made. Returns the application as saved."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "posting_id": {"type": "integer", "description": "The posting's id."},
                "status": {
                    "type": "string",
                    "enum": list(VALID_STATUSES),
                    "description": "The new status. Omit to leave it unchanged.",
                },
                "applied_date": {
                    "type": "string",
                    "description": (
                        "YYYY-MM-DD. When the user says they applied, set this "
                        "to the date they applied (today unless they say otherwise)."
                    ),
                },
                "notes": {
                    "type": "string",
                    "description": "Added after the existing notes; earlier notes are kept.",
                },
            },
            "required": ["posting_id"],
        },
    },
]

# The only functions the model can reach, keyed by the tool names in TOOLS.
TOOL_FUNCTIONS = {
    "search_postings": search_postings,
    "get_posting": get_posting,
    "get_applications": get_applications,
    "search_posting_text": search_posting_text,
    "update_application": update_application,
}


if __name__ == "__main__":
    # json.dumps fails loudly if anything isn't JSON-serializable.
    def show(label, result):
        print(f"--- {label}")
        print(json.dumps(result, indent=2))

    # Catches a tool added to one place but not the other.
    assert {t["name"] for t in TOOLS} == set(TOOL_FUNCTIONS), "TOOLS and TOOL_FUNCTIONS differ"

    show("search_postings(skill='Postgres')", search_postings(skill="Postgres"))
    show("search_postings(company='bevel')", search_postings(company="bevel"))
    show("search_postings(company='Brevel')", search_postings(company="Brevel"))
    show("get_posting(1)", get_posting(1))
    show("get_posting(999)", get_posting(999))
    show("get_applications()", get_applications())
    show("get_applications('pending')", get_applications("pending"))
    show("search_posting_text('visa sponsorship')", search_posting_text("visa sponsorship"))
    show("search_posting_text('remote work', posting_id=1)",
         search_posting_text("remote work", posting_id=1))
    show("search_posting_text('remote work', posting_id=999)",
         search_posting_text("remote work", posting_id=999))
    # Only the error cases, so running this file never changes the data.
    show("update_application(1)", update_application(1))
    show("update_application(1, status='ghosted')", update_application(1, status="ghosted"))
    show("update_application(1, applied_date='last friday')",
         update_application(1, applied_date="last friday"))
    show("update_application(999, status='applied')", update_application(999, status="applied"))
