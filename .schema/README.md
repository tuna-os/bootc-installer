# Fisherman Recipe Schema

This directory contains the authoritative JSON schema for bootc-installer's fisherman installation recipes.

## Overview

The fisherman recipe protocol defines the contract between:

1. **bootc-installer GUI** (Python) — generates recipes from user input
2. **fisherman** (Go) — consumes recipes and performs installations  
3. **bootc-installer TUI** (Rust) — may also consume recipes

## Schema Location

- **JSON Schema**: `.schema/fisherman-recipe-schema.json`
- **Version**: Follows fisherman's semver (checked against pinned submodule)
- **Stability**: Draft (0.1 — not yet released as part of a fisherman stable contract)

## Using the Schema

### Validating a Recipe Locally

```bash
python3 tests/validate_recipe.py <recipe.json>
```

### In CI

The Python test workflow automatically validates all generated recipes:

```bash
pytest tests/test_recipe_schema.py
```

### For External Tools

The schema is machine-readable and can be consumed by:

- JSON schema validators (`jsonschema`, `ajv`, etc.)
- Code generators (OpenAPI/Swagger tooling)
- IDE autocomplete and linting

## Schema Governance

### When to Update

Update the schema when:

1. **fisherman's Recipe struct changes** (new fields, enum values, required invariants)
2. **bootc-installer adds producer capabilities** (new GUI fields that map to fisherman)
3. **bootc-installer TUI evolves** (new optional fields)

### How to Update

1. Extract the Go type definition from `fisherman/fisherman/internal/recipe/recipe.go`
2. Update `.schema/fisherman-recipe-schema.json` to match
3. Document breaking changes in commit message
4. Run `pytest tests/test_recipe_schema.py` to ensure the GUI still validates

### Submodule Protocol Upgrades

When updating the `fisherman` submodule:

1. Check fisherman's CHANGELOG for Recipe struct changes
2. Update the schema accordingly
3. Update bootc-installer's `gen_install_recipe` to produce all new fields (or provide defaults)
4. Run the validation test to ensure compatibility

## Field Reference

See `.schema/fisherman-recipe-schema.json` for the complete field reference, including:

- Required vs optional fields
- Type constraints (enums, string patterns, numeric bounds)
- Field descriptions and usage notes

## Known Gaps

This schema is a first step toward full producer/consumer validation:

- **Not yet versioned**: Schema version field not yet implemented in fisherman
- **TUI schema**: bootc-installer TUI defines its own reduced schema; this should converge
- **Submodule compatibility**: Protocol upgrades are not yet tracked as explicit gates in CI

These gaps are tracked in issue #48 (GUI/fisherman protocol contract).
