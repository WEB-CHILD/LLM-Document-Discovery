"""
Tests for main.py helper functions.

Validates core logic for file ID derivation and category YAML loading
before running the full pipeline.
"""

import pytest
import yaml
from pathlib import Path
from main import derive_result_id, load_all_categories
import config


def test_derive_result_id_removes_md_extension():
    """Verify result ID removes .md extension"""
    filepath = Path("input/markdown_corpus/19961019235833_http_example.com.md")

    result_id = derive_result_id(filepath)

    assert result_id == "19961019235833_http_example.com"
    assert not result_id.endswith(".md")


def test_derive_result_id_handles_no_extension():
    """Verify result ID handles files without .md extension"""
    filepath = Path("input/test_file")

    result_id = derive_result_id(filepath)

    assert result_id == "test_file"


def test_derive_result_id_handles_multiple_dots():
    """Verify result ID handles filenames with multiple dots"""
    filepath = Path("input/file.name.with.dots.md")

    result_id = derive_result_id(filepath)

    # Path.stem removes only the last extension
    assert result_id == "file.name.with.dots"


def test_load_all_categories_uses_config():
    """Verify load_all_categories() uses config.PROMPTS_DIR"""
    # This test uses the actual POC-prompts directory
    categories = load_all_categories()

    # Count actual YAML files to verify we loaded them all
    yaml_count = len(list(config.PROMPTS_DIR.glob("*.yaml")))
    assert len(categories) == yaml_count, f"Should load all {yaml_count} YAML files"

    # Verify all files were loaded (at least 1 category)
    assert len(categories) > 0, "Should have at least one category"

    # Verify structure of each category
    for cat in categories:
        assert "id" in cat
        assert "name" in cat
        assert "description" in cat
        assert "prompt" in cat
        assert isinstance(cat["id"], int)
        assert isinstance(cat["name"], str)
        assert isinstance(cat["description"], str)
        assert isinstance(cat["prompt"], str)


def test_load_all_categories_sorted_by_id():
    """Verify categories are sorted by ID"""
    categories = load_all_categories()

    category_ids = [cat["id"] for cat in categories]

    # Should be sorted ascending
    assert category_ids == sorted(category_ids)

    # Should start at 1
    assert category_ids[0] == 1
    # Last ID should match the count (sequential 1-N)
    assert category_ids[-1] == len(categories)


def test_load_all_categories_no_duplicates():
    """Verify no duplicate category IDs"""
    categories = load_all_categories()

    category_ids = [cat["id"] for cat in categories]

    # All IDs should be unique
    assert len(category_ids) == len(set(category_ids))


def test_load_all_categories_spot_check_category_1():
    """Verify category 1 (imperative_verbs) loads correctly"""
    categories = load_all_categories()

    # Find category 1
    cat_1 = next(cat for cat in categories if cat["id"] == 1)

    assert cat_1["name"] == "imperative_verbs"
    assert "Commands and instructions" in cat_1["description"]
    assert len(cat_1["prompt"]) > 0
    assert "imperative verbs" in cat_1["prompt"]


def test_load_categories_from_temp_dir(temp_yaml_dir, monkeypatch):
    """Test category loading with custom YAML files"""
    # Create test YAML files
    cat1 = {
        "id": 1,
        "name": "test_category_1",
        "description": "Test description 1",
        "prompt": "Test prompt 1"
    }
    cat2 = {
        "id": 2,
        "name": "test_category_2",
        "description": "Test description 2",
        "prompt": "Test prompt 2"
    }

    with open(temp_yaml_dir / "01_test.yaml", "w") as f:
        yaml.dump(cat1, f)

    with open(temp_yaml_dir / "02_test.yaml", "w") as f:
        yaml.dump(cat2, f)

    # Monkeypatch config.PROMPTS_DIR to use temp directory
    monkeypatch.setattr(config, "PROMPTS_DIR", temp_yaml_dir)

    categories = load_all_categories()

    assert len(categories) == 2
    assert categories[0]["id"] == 1
    assert categories[0]["name"] == "test_category_1"
    assert categories[1]["id"] == 2
    assert categories[1]["name"] == "test_category_2"


def test_load_categories_handles_missing_id_field(temp_yaml_dir, monkeypatch):
    """Test error handling for YAML missing 'id' field"""
    # Create malformed YAML (missing id)
    bad_cat = {
        "name": "bad_category",
        "description": "Missing ID field",
        "prompt": "This will fail"
    }

    with open(temp_yaml_dir / "01_bad.yaml", "w") as f:
        yaml.dump(bad_cat, f)

    monkeypatch.setattr(config, "PROMPTS_DIR", temp_yaml_dir)

    # Should raise KeyError when trying to access missing 'id'
    with pytest.raises(KeyError):
        load_all_categories()


def test_load_categories_handles_invalid_yaml(temp_yaml_dir, monkeypatch):
    """Test error handling for invalid YAML syntax"""
    # Create file with invalid YAML
    with open(temp_yaml_dir / "01_invalid.yaml", "w") as f:
        f.write("this is not: valid: yaml: syntax:\n")
        f.write("  - broken\n")
        f.write("  malformed\n")

    monkeypatch.setattr(config, "PROMPTS_DIR", temp_yaml_dir)

    # Should raise yaml.YAMLError
    with pytest.raises(yaml.YAMLError):
        load_all_categories()


def test_load_categories_empty_directory(temp_yaml_dir, monkeypatch):
    """Test behavior with no YAML files"""
    # Use empty temp directory
    monkeypatch.setattr(config, "PROMPTS_DIR", temp_yaml_dir)

    # Should raise SystemExit when no YAML files found
    with pytest.raises(SystemExit):
        load_all_categories()


def test_all_category_prompts_non_empty():
    """Verify all category prompts have content"""
    categories = load_all_categories()

    for cat in categories:
        assert len(cat["prompt"].strip()) > 0, f"Category {cat['id']} has empty prompt"


def test_all_category_names_unique():
    """Verify all category names are unique"""
    categories = load_all_categories()

    names = [cat["name"] for cat in categories]

    assert len(names) == len(set(names)), "Duplicate category names found"


def test_all_category_ids_sequential():
    """Verify category IDs are sequential 1-N"""
    categories = load_all_categories()

    ids = [cat["id"] for cat in categories]
    expected_count = len(categories)

    assert ids == list(range(1, expected_count + 1)), f"Category IDs not sequential 1-{expected_count}"
