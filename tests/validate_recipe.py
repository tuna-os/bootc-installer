#!/usr/bin/env python3
"""Validate fisherman recipe against schema.

Usage:
  python3 validate_recipe.py <recipe.json>

Exit codes:
  0: recipe is valid
  1: recipe validation failed
  2: schema or recipe file not found
"""

import json
import sys
import os
from pathlib import Path

try:
    import jsonschema
except ImportError:
    print("ERROR: jsonschema not installed. Install with: pip install jsonschema")
    sys.exit(2)


def validate_recipe(recipe_path: str, schema_path: str | None = None) -> bool:
    """Validate a fisherman recipe against the schema.
    
    Args:
        recipe_path: Path to the recipe JSON file
        schema_path: Path to the JSON schema (auto-detected if None)
    
    Returns:
        True if valid, False if validation fails
    """
    # Find schema if not provided
    if schema_path is None:
        # Look in .schema/ relative to this script
        script_dir = Path(__file__).parent
        schema_path = script_dir / ".." / ".schema" / "fisherman-recipe-schema.json"
        if not schema_path.exists():
            # Also check relative to cwd
            schema_path = Path(".schema/fisherman-recipe-schema.json")
    
    schema_path = Path(schema_path)
    recipe_path = Path(recipe_path)
    
    if not schema_path.exists():
        print(f"ERROR: Schema not found at {schema_path}")
        return False
    
    if not recipe_path.exists():
        print(f"ERROR: Recipe file not found at {recipe_path}")
        return False
    
    try:
        with open(schema_path) as f:
            schema = json.load(f)
        
        with open(recipe_path) as f:
            recipe = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON: {e}")
        return False
    except Exception as e:
        print(f"ERROR: Failed to read files: {e}")
        return False
    
    try:
        jsonschema.validate(instance=recipe, schema=schema)
        print(f"✓ Recipe is valid against schema")
        return True
    except jsonschema.ValidationError as e:
        print(f"✗ Recipe validation failed:")
        print(f"  Path: {'.'.join(str(p) for p in e.absolute_path) or 'root'}")
        print(f"  Error: {e.message}")
        if e.validator_value:
            print(f"  Expected: {e.validator_value}")
        return False
    except jsonschema.SchemaError as e:
        print(f"ERROR: Invalid schema: {e.message}")
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    
    recipe_path = sys.argv[1]
    schema_path = sys.argv[2] if len(sys.argv) > 2 else None
    
    if validate_recipe(recipe_path, schema_path):
        sys.exit(0)
    else:
        sys.exit(1)
