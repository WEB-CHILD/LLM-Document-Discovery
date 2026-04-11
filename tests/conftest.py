"""Shared test fixtures for the llm_discovery test suite."""

import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary SQLite DB from schema.sql."""
    schema_path = Path(__file__).parent.parent / "schema.sql"
    db_path = tmp_path / "test_corpus.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    with open(schema_path) as f:
        cursor.executescript(f.read())
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def sample_corpus_dir(tmp_path):
    """Create a temp directory with sample markdown files (with timestamp/url header)."""
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()

    files = {
        "doc1.md": "20040701020553/http://www.kidlink.org:80/KIDFORUM/\n\n"
                    "# Welcome to KIDFORUM\n\n"
                    "This is a forum for kids aged 10-15 to discuss topics.\n"
                    "We love sharing ideas and making new friends!\n"
                    "Let's explore the world together.\n" * 5,
        "doc2.md": "20040701022600/http://www.kidlink.org:80/KIDPROJ/\n\n"
                    "# Kidlink Project\n\n"
                    "Students from around the world share their capitals.\n"
                    "My name is Maria and I am 12 years old from Denmark.\n"
                    "Vi elsker at lære om andre lande!\n" * 5,
        "doc3.md": "19970404181846/http://www.kidpub.org:80/\n\n"
                    "# KidPub Stories\n\n"
                    "Here are the newest stories written by kids.\n"
                    "Check out these amazing tales from young authors.\n"
                    "Children ages 5-17 can publish their work here.\n" * 5,
    }

    for name, content in files.items():
        (corpus_dir / name).write_text(content)

    return corpus_dir


@pytest.fixture
def sample_prompts_dir(tmp_path):
    """Create a temp directory with a subset of prompt YAML files."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()

    prompts = {
        "02_explicit_age_child_references.yaml": (
            "id: 2\n"
            "name: explicit_age_child_references\n"
            "description: Direct mentions of ages 5-17 or child-related terms\n"
            "prompt: |\n"
            '  Extract text containing age numbers 5-17, or words: "kids", "children".\n'
            "  Analyze the following document and extract matching passages:\n"
        ),
        "03_corporate_register_markers.yaml": (
            "id: 3\n"
            "name: corporate_register_markers\n"
            "description: Corporate or institutional language patterns\n"
            "prompt: |\n"
            '  Extract text containing corporate language: "terms of service", "policy".\n'
            "  Analyze the following document and extract matching passages:\n"
        ),
    }

    for name, content in prompts.items():
        (prompts_dir / name).write_text(content)

    return prompts_dir
