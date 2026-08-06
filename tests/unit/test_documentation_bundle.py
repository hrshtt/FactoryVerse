from FactoryVerse.utils.docs.bundle import write_reference_bundle


def test_reference_bundle_routes_accessors_and_schema_sections(tmp_path):
    api = tmp_path / "api.md"
    schema = tmp_path / "schema.md"
    api.write_text(
        "# API\n\n## Action Classes\n\n### MovementAction\n\n"
        "**Accessor:** `walking`\n\n#### `walking.walk_to`\n",
        encoding="utf-8",
    )
    schema.write_text(
        "# Schema\n\n## Query Constraints\n\nSELECT only.\n",
        encoding="utf-8",
    )

    digests = write_reference_bundle(api, schema, tmp_path / "bundle")

    assert "api/walking.md" in digests
    assert "api/walking/walk-to.md" in digests
    assert "schema/query-constraints.md" in digests
    index = (tmp_path / "bundle" / "INDEX.md").read_text()
    assert "api/walking.md" in index
    assert "API source SHA-256" in index
