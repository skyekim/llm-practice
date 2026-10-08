"""Exercise 5, step 1: the database connection shared by every tool.

Requires the tables from 03-tools/setup_db.py and the chunks index from
04-rag/build_index.py.
"""
import os

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

load_dotenv()


def connect():
    # dict_row returns each row as {"column": value} instead of a tuple.
    conn = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)
    # Lets psycopg send numpy arrays as vector values for the chunk search.
    register_vector(conn)
    return conn
