"""Unit checks of the v2 Alembic revisions: their order and each one's contents.

Each revision stays as Alembic generated it, apart from documented
post-generation corrections; these tests read the revision files and check the
operations each one runs.
"""

import re
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from policyengine_api.constants import REPO
from policyengine_api.data.v2.migration_target import V2_ALEMBIC_HEAD_REVISION
from policyengine_api.data.v2.models import V2_TABLE_NAMES

POST_BASELINE_TABLE_NAMES = frozenset(
    {
        "budget_window_runs",
        "cliff_impacts",
        "countries",
        "legacy_household_mappings",
        "legacy_policy_mappings",
        "legacy_user_mappings",
        "legacy_user_policy_mappings",
        "parameter_search_files",
        "parameter_tree_children",
        "labor_supply_decile_responses",
        "labor_supply_responses",
        "simulation_runs",
        "stage12_evaluation_reports",
        "stage12_evaluation_simulations",
        "user_dynamics",
        "user_identities",
        "user_invitations",
        "user_report_run_associations",
        "user_type_changes",
        "withheld_area_codes",
    }
)
# The catalog format 2 revision's parent, the countries revision.
CATALOG_FORMAT_2_PARENT_REVISION = "fb1a3e40d3d6"
CATALOG_FORMAT_2_REVISION = "f5c1d9b4685b"
AREA_IMPACT_COORDINATE_REVISION = "e86f19a6c4da"
PARAMETER_TREE_REVISION = "3869eb814a90"
PARAMETER_SEARCH_FILE_REVISION = "c614b6bcccfc"
# The catalog pruning revision, parent of the simulation runs revision.
CATALOG_PRUNING_REVISION = "334859ef4fec"
# The simulation runs revision, parent of the saved-item keys revision.
SIMULATION_RUNS_REVISION = "1356f658347d"
# The saved-item keys revision, parent of the user types revision.
SAVED_ITEM_KEYS_REVISION = "81b728a088e7"
# The user types revision, on the saved-item keys revision.
USER_TYPES_REVISION = "617f531f1506"
# The user type changes revision, on the user types revision, and parent of
# the SPM availability revision.
USER_TYPE_CHANGES_REVISION = "970be5d29283"
# The SPM availability revision, on the user type changes revision, and parent
# of the withheld area codes revision.
SPM_AVAILABILITY_REVISION = "0c136a278f29"
# The withheld area codes revision, on the SPM availability revision, and
# parent of the shared reports revision.
WITHHELD_AREA_CODES_REVISION = "1e1e3f079f2c"
# The shared reports revision, on the withheld area codes revision, and parent
# of the user invitations revision.
SHARED_REPORTS_REVISION = "94dc43079186"
# The user invitations revision, on the shared reports revision, and parent
# of the dynamics revision.
USER_INVITATIONS_REVISION = "f519a77ba122"
# The dynamics revision, on the user invitations revision, and parent of the
# cliff impacts revision.
DYNAMICS_REVISION = "9d1d12a7ac58"
# The cliff impacts revision, on the dynamics revision, and parent of the
# report column drops revision.
CLIFF_IMPACTS_REVISION = "bc334f9877b7"
# The report column drops revision, on the cliff impacts revision, and
# parent of the user dynamics revision.
REPORT_COLUMN_DROPS_REVISION = "4e30076d4b9f"
# The user dynamics revision, on the report column drops revision.
USER_DYNAMICS_REVISION = "d417fe8b1b17"


def test_v2_revision_chain_has_generated_policy_and_user_identity_changes() -> None:
    config = Config(str(REPO / "alembic-v2.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [V2_ALEMBIC_HEAD_REVISION]
    assert V2_ALEMBIC_HEAD_REVISION == USER_DYNAMICS_REVISION
    assert [revision.revision for revision in script.walk_revisions()] == [
        USER_DYNAMICS_REVISION,
        REPORT_COLUMN_DROPS_REVISION,
        CLIFF_IMPACTS_REVISION,
        DYNAMICS_REVISION,
        USER_INVITATIONS_REVISION,
        SHARED_REPORTS_REVISION,
        WITHHELD_AREA_CODES_REVISION,
        SPM_AVAILABILITY_REVISION,
        USER_TYPE_CHANGES_REVISION,
        USER_TYPES_REVISION,
        SAVED_ITEM_KEYS_REVISION,
        SIMULATION_RUNS_REVISION,
        CATALOG_PRUNING_REVISION,
        PARAMETER_SEARCH_FILE_REVISION,
        PARAMETER_TREE_REVISION,
        AREA_IMPACT_COORDINATE_REVISION,
        CATALOG_FORMAT_2_REVISION,
        CATALOG_FORMAT_2_PARENT_REVISION,
        "fbb7488ebe8a",
        "91af4fc8d8c1",
        "60d6518b6a98",
        "439303be14fe",
        "724b1b11a33e",
        "af34023a728f",
        "c21c4a807a49",
        "711ec2f0a5a5",
        "68b4a5ae5dc5",
        "f5ef4347cb2a",
    ]

    baseline = (
        REPO / "migrations/v2/versions/f5ef4347cb2a_establish_v2_platform_baseline.py"
    ).read_text(encoding="utf-8")
    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in baseline
    )
    assert "down_revision: Union[str, None] = None" in baseline
    assert "op.execute(" not in baseline
    assert "op.bulk_insert(" not in baseline
    assert "op.v2_reference_row_change(" not in baseline
    assert "region_datasets" not in baseline
    assert "historical_reference_data_operations" not in baseline
    assert "ck_users_primary_country" in baseline
    assert "ck_report_runs_idempotency_key_nonblank" not in baseline
    assert re.search(
        r'sa\.Column\(\s*"idempotency_key",\s*sa\.Uuid\(\)',
        baseline,
    )
    assert "fk_regions_default_dataset_model_datasets" in baseline
    assert "uq_datasets_model_name" in baseline
    assert "ck_datasets_output_storage_path" in baseline
    baseline_table_count = len(V2_TABLE_NAMES - POST_BASELINE_TABLE_NAMES)
    assert baseline.count("op.create_table(") == baseline_table_count
    assert baseline.count("op.drop_table(") == baseline_table_count

    corrected_enum_names = set(
        re.findall(
            r"sa\.Enum\(name=[\"']([^\"']+)[\"']\)\.drop\(op\.get_bind\(\)\)",
            baseline,
        )
    )
    assert corrected_enum_names == {
        "v2_aggregate_type",
        "v2_decile_type",
        "v2_household_job_status",
        "v2_output_status",
        "v2_region_type",
        "v2_report_run_status",
        "v2_report_run_trigger",
        "v2_simulation_status",
        "v2_simulation_type",
    }

    stage_9_revision = (
        REPO
        / "migrations/v2/versions/68b4a5ae5dc5_version_metadata_catalog_snapshots.py"
    ).read_text(encoding="utf-8")
    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in stage_9_revision
    )
    assert 'down_revision: Union[str, None] = "f5ef4347cb2a"' in stage_9_revision
    assert "uq_parameter_values_canonical_parameter_start_date" in stage_9_revision
    assert "op.create_index(" in stage_9_revision
    assert "op.drop_index(" in stage_9_revision
    assert "tax_benefit_model_version_id" in stage_9_revision
    assert "metadata_time_periods" in stage_9_revision
    assert "current_law_id" in stage_9_revision
    assert "op.execute(" not in stage_9_revision
    assert "op.bulk_insert(" not in stage_9_revision


def test_phase_10_revision_has_only_documented_generation_corrections() -> None:
    revision = (
        REPO / "migrations/v2/versions/711ec2f0a5a5_migrate_v2_policies.py"
    ).read_text(encoding="utf-8")

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert 'down_revision: Union[str, None] = "68b4a5ae5dc5"' in revision
    assert revision.count("Post-generation correction:") == 4
    assert 'postgresql_using="user_id::text"' in revision
    assert 'postgresql_using="user_id::uuid"' in revision
    assert "op.execute(" not in revision
    assert "op.bulk_insert(" not in revision

    policy_key = revision.index('"uq_policies_id_country"')
    policy_mapping = revision.index(
        'op.create_table(\n        "legacy_policy_mappings"'
    )
    association_key = revision.index('"uq_user_policies_id_country"')
    association_mapping = revision.index(
        'op.create_table(\n        "legacy_user_policy_mappings"'
    )
    drop_association_mapping = revision.index(
        'op.drop_table("legacy_user_policy_mappings")'
    )
    drop_association_key = revision.index(
        'op.drop_constraint("uq_user_policies_id_country"'
    )

    assert policy_key < policy_mapping
    assert association_key < association_mapping
    assert drop_association_mapping < drop_association_key


def test_saved_policy_revision_tracking_was_generated_after_phase_10() -> None:
    revision = (
        REPO
        / "migrations/v2/versions/c21c4a807a49_track_saved_policy_mirror_revisions.py"
    ).read_text(encoding="utf-8")

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert 'down_revision: Union[str, None] = "711ec2f0a5a5"' in revision
    assert "last_applied_source_revision" in revision
    assert "ck_legacy_user_policy_mappings_source_revision" in revision
    assert "op.execute(" not in revision
    assert "op.bulk_insert(" not in revision


def test_legacy_user_uuid_mapping_revision_is_generated_and_reversible() -> None:
    revision = (
        REPO / "migrations/v2/versions/af34023a728f_map_legacy_users_to_v2_uuids.py"
    ).read_text(encoding="utf-8")

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert 'down_revision: Union[str, None] = "c21c4a807a49"' in revision
    assert revision.count("Post-generation correction:") == 2
    assert 'postgresql_using="user_id::uuid"' in revision
    assert 'postgresql_using="user_id::text"' in revision
    assert 'op.create_table(\n        "legacy_user_mappings"' in revision
    assert 'op.drop_table("legacy_user_mappings")' in revision
    assert "fk_user_policies_user_id_users" in revision
    assert "uq_legacy_user_mappings_user_id" in revision
    assert "op.execute(" not in revision
    assert "op.bulk_insert(" not in revision


def test_phase_11_household_revision_is_generated_and_reversible() -> None:
    revision = (
        REPO / "migrations/v2/versions/724b1b11a33e_migrate_v2_households.py"
    ).read_text(encoding="utf-8")

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert 'down_revision: Union[str, None] = "af34023a728f"' in revision
    household_key = revision.index('"uq_households_id_country"')
    mapping_table = revision.index(
        'op.create_table(\n        "legacy_household_mappings"'
    )
    drop_mapping = revision.index('op.drop_table("legacy_household_mappings")')
    drop_household_key = revision.index('op.drop_constraint("uq_households_id_country"')
    assert household_key < mapping_table
    assert drop_mapping < drop_household_key
    assert "op.execute(" not in revision
    assert "op.bulk_insert(" not in revision


def test_stage_12_comparison_table_revision_is_generated_and_reversible() -> None:
    revision = (
        REPO
        / "migrations/v2/versions/439303be14fe_add_stage_12_evaluation_executions.py"
    ).read_text(encoding="utf-8")

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert 'down_revision: Union[str, None] = "724b1b11a33e"' in revision
    assert revision.count("Post-generation reversibility correction:") == 1
    assert 'op.create_table(\n        "stage12_evaluation_reports"' in revision
    assert 'op.create_table(\n        "stage12_evaluation_simulations"' in revision
    assert 'op.drop_table("stage12_evaluation_simulations")' in revision
    assert 'op.drop_table("stage12_evaluation_reports")' in revision
    corrected_enum_names = set(
        re.findall(
            r"sa\.Enum\(name=[\"']([^\"']+)[\"']\)\.drop\(op\.get_bind\(\)\)",
            revision,
        )
    )
    assert corrected_enum_names == {
        "v2_stage12_aggregation_status",
        "v2_stage12_evaluation_status",
        "v2_stage12_simulation_role",
    }
    assert "op.execute(" not in revision
    assert "op.bulk_insert(" not in revision


def test_stage_12_result_comparison_revision_is_generated_and_reversible() -> None:
    revision = (
        REPO
        / "migrations/v2/versions/60d6518b6a98_track_stage_12_result_comparisons.py"
    ).read_text(encoding="utf-8")

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert 'down_revision: Union[str, None] = "439303be14fe"' in revision
    assert revision.count("Dialect correction:") == 1
    assert revision.count("Reversibility correction") == 1
    assert "comparison_status_enum.create(op.get_bind(), checkfirst=False)" in revision
    assert "comparison_status_enum.drop(op.get_bind(), checkfirst=False)" in revision
    assert revision.count('op.add_column(\n        "stage12_evaluation_reports"') == 7
    for column_name in (
        "comparison_status",
        "comparison_output_uri",
        "comparison_output_sha256",
        "comparison_schema_version",
        "comparison_completed_at",
        "comparison_error_code",
        "comparison_error_summary",
    ):
        assert f'"{column_name}"' in revision
        assert (
            f'op.drop_column("stage12_evaluation_reports", "{column_name}")' in revision
        )
    assert "ck_stage12_eval_reports_comparison_state" not in revision
    assert "op.execute(" not in revision
    assert "op.bulk_insert(" not in revision


def test_stage_12_observability_revision_is_generated_and_reversible() -> None:
    revision = (
        REPO / "migrations/v2/versions/91af4fc8d8c1_add_stage12_observability_id.py"
    ).read_text(encoding="utf-8")

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert 'down_revision: Union[str, None] = "60d6518b6a98"' in revision
    assert '"observability_id"' in revision
    assert "AutoString(length=36)" in revision
    assert (
        'op.drop_column("stage12_evaluation_reports", "observability_id")' in revision
    )
    assert "op.execute(" not in revision
    assert "op.bulk_insert(" not in revision


def test_stage_12a_user_identity_and_association_revision_is_generated() -> None:
    revision = (
        REPO
        / "migrations/v2/versions/fbb7488ebe8a_link_signed_in_users_to_v1_anchored_.py"
    ).read_text(encoding="utf-8")

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert 'down_revision: Union[str, None] = "91af4fc8d8c1"' in revision
    # One generated revision covers both the identity table and the reshape.
    assert revision.count("op.create_table(") == 1
    assert 'op.create_table(\n        "user_identities"' in revision
    assert '"uq_user_identities_issuer_subject"' in revision
    assert 'op.drop_table("user_identities")' in revision
    for _table_name, reference in (
        ("user_policies", "policy"),
        ("user_household_associations", "household"),
        ("user_simulation_associations", "simulation"),
        ("user_report_associations", "report"),
    ):
        assert f'"legacy_{reference}_id"' in revision
    # The browser-local import keys were removed before release.
    assert "client_ref" not in revision
    for check_name in (
        "ck_user_policies_policy_ref",
        "ck_user_policies_baseline",
        "ck_user_household_associations_household_ref",
        "ck_user_simulation_associations_simulation_ref",
        "ck_user_simulation_associations_country",
        "ck_user_report_associations_report_ref",
        "ck_user_report_associations_country",
        "ck_user_report_associations_budget_window_years",
        "ck_users_user_type",
        "ck_users_standard_primary_country",
    ):
        assert check_name in revision
    # Cross-service foreign keys to v2 simulations and reports are removed.
    assert "fk_user_simulation_associations_simulation_id_simulations" in revision
    assert "fk_user_report_associations_report_id_reports" in revision
    assert "fk_user_report_associations_user_policy_id_user_policies" in revision
    assert (
        "fk_user_report_associations_baseline_user_policy_id_user_policies" in revision
    )
    assert 'ondelete="SET NULL"' in revision
    assert "Post-generation" not in revision
    assert "op.execute(" not in revision
    assert "op.bulk_insert(" not in revision
    # The previous API v1 revision still maps the retired country and label
    # columns, so the upgrade relaxes them instead of dropping anything.
    upgrade = revision[
        revision.index("def upgrade()") : revision.index("def downgrade()")
    ]
    assert "op.drop_column(" not in upgrade
    assert "op.drop_table(" not in upgrade
    for table_name in ("user_simulation_associations", "user_report_associations"):
        assert (
            f'"{table_name}",\n        "country",\n'
            "        existing_type=sa.VARCHAR(length=16),\n"
            "        nullable=True,"
        ) in upgrade
    # Users gain a type whose server default keeps the previous revision's
    # inserts standard, and only unauthenticated users omit a country.
    assert (
        '"user_type",\n'
        "            sqlmodel.sql.sqltypes.AutoString(length=16),\n"
        '            server_default="standard",\n'
        "            nullable=False,"
    ) in upgrade
    assert (
        '"users", "primary_country", existing_type=sa.VARCHAR(length=2), nullable=True'
    ) in upgrade


COUNTRY_REFERENCE_COLUMNS = (
    ("users", "primary_country"),
    ("households", "country_id"),
    ("policies", "country_id"),
    ("user_household_associations", "country_id"),
    ("user_policies", "country_id"),
    ("user_simulation_associations", "country_id"),
    ("user_report_associations", "country_id"),
)
# The generated downgrade restores each check in PostgreSQL's reflected form
# of ``<column> IN ('us', 'uk')``.
US_AND_UK = "ANY (ARRAY['us'::character varying, 'uk'::character varying]::text[])"
REPLACED_COUNTRY_CHECKS = {
    "ck_users_primary_country": ("users", f"primary_country::text = {US_AND_UK}"),
    "ck_households_country": ("households", f"country_id::text = {US_AND_UK}"),
    "ck_policies_country": ("policies", f"country_id::text = {US_AND_UK}"),
    "ck_user_household_associations_country": (
        "user_household_associations",
        f"country_id::text = {US_AND_UK}",
    ),
    "ck_user_policies_country": ("user_policies", f"country_id::text = {US_AND_UK}"),
    "ck_user_simulation_associations_country": (
        "user_simulation_associations",
        f"country_id::text = {US_AND_UK}",
    ),
    "ck_user_report_associations_country": (
        "user_report_associations",
        f"country_id::text = {US_AND_UK}",
    ),
}


def _countries_revision_source() -> str:
    script = ScriptDirectory.from_config(Config(str(REPO / "alembic-v2.ini")))
    countries_revision = next(
        revision
        for revision in script.walk_revisions()
        if revision.down_revision == "fbb7488ebe8a"
    )
    assert countries_revision.revision == CATALOG_FORMAT_2_PARENT_REVISION
    assert countries_revision.path is not None
    return Path(countries_revision.path).read_text(encoding="utf-8")


def test_countries_revision_inserts_us_and_uk_and_replaces_country_checks() -> None:
    revision = _countries_revision_source()
    upgrade = revision[
        revision.index("def upgrade()") : revision.index("def downgrade()")
    ]
    downgrade = revision[revision.index("def downgrade()") :]

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert revision.count("op.create_table(") == 1
    assert 'op.create_table(\n        "countries"' in upgrade
    assert "ck_countries_society_wide_requires_household" in upgrade
    assert 'op.drop_table("countries")' in downgrade
    # The one hand-written operation, an approved exception to generated-only
    # revisions: the US and UK rows, inserted before the foreign keys that
    # existing rows must satisfy. The generated downgrade drops them with the
    # table.
    assert revision.count("Approved hand-written data operation") == 1
    assert revision.count("Post-generation correction") == 0
    assert revision.count("op.bulk_insert(") == 1
    assert "op.execute(" not in revision
    inserted_rows = upgrade[
        upgrade.index("op.bulk_insert(") : upgrade.index("op.create_foreign_key(")
    ]
    for country_id in ("uk", "us"):
        assert f'"id": "{country_id}"' in inserted_rows
    assert inserted_rows.count('"household_enabled": True') == 2
    assert inserted_rows.count('"society_wide_enabled": True') == 2
    for table_name, column_name in COUNTRY_REFERENCE_COLUMNS:
        key_name = f"fk_{table_name}_{column_name}_countries"
        assert key_name in upgrade
        assert key_name in downgrade
    assert upgrade.count('ondelete="RESTRICT"') == len(COUNTRY_REFERENCE_COLUMNS)
    for check_name, (table_name, expression) in REPLACED_COUNTRY_CHECKS.items():
        assert check_name in upgrade
        assert f'"{table_name}"' in upgrade
        assert check_name in downgrade
        assert expression in downgrade
    assert "op.drop_column(" not in upgrade
    assert "op.add_column(" not in upgrade


AREA_IMPACT_COORDINATE_COLUMNS = frozenset(
    (table_name, column_name)
    for table_name in ("constituency_impacts", "local_authority_impacts")
    for column_name in ("x", "y")
)


def test_area_impact_coordinate_removal_is_generated_and_reversible() -> None:
    revision = (
        REPO
        / "migrations/v2/versions/e86f19a6c4da_drop_uk_area_impact_map_coordinates.py"
    ).read_text(encoding="utf-8")

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert 'down_revision: Union[str, None] = "f5c1d9b4685b"' in revision
    assert "Post-generation" not in revision
    upgrade = revision[
        revision.index("def upgrade()") : revision.index("def downgrade()")
    ]
    downgrade = revision[revision.index("def downgrade()") :]
    # The upgrade drops the four map coordinate columns and does nothing else.
    assert len(re.findall(r"\bop\.\w+\(", upgrade)) == 4
    dropped_columns = re.findall(
        r'op\.drop_column\(\s*"(\w+)",\s*"(\w+)"\s*\)', upgrade
    )
    assert frozenset(dropped_columns) == AREA_IMPACT_COORDINATE_COLUMNS
    # The downgrade adds each one back as the baseline created it: a required
    # integer without a server default.
    assert len(re.findall(r"\bop\.\w+\(", downgrade)) == 4
    restored_columns = re.findall(
        r'op\.add_column\(\s*"(\w+)",\s*sa\.Column\(\s*"(\w+)",\s*'
        r"sa\.INTEGER\(\),\s*autoincrement=False,\s*nullable=False,?\s*\),?\s*\)",
        downgrade,
    )
    assert frozenset(restored_columns) == AREA_IMPACT_COORDINATE_COLUMNS


def test_catalog_format_2_revision_adds_only_nullable_columns() -> None:
    """The revision after the countries revision adds catalog format 2's columns.

    It is generated, adds each column as nullable so versions published earlier
    keep them empty, drops them on downgrade, and writes no data.
    """
    script = ScriptDirectory.from_config(Config(str(REPO / "alembic-v2.ini")))
    children = [
        revision
        for revision in script.walk_revisions()
        if revision.down_revision == CATALOG_FORMAT_2_PARENT_REVISION
    ]
    assert len(children) == 1
    revision = Path(children[0].path).read_text(encoding="utf-8")
    upgrade = revision[
        revision.index("def upgrade()") : revision.index("def downgrade()")
    ]
    downgrade = revision[revision.index("def downgrade()") :]

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    added_columns = {
        "tax_benefit_model_versions": ("catalog_format", "entities", "basic_inputs"),
        "variables": (
            "is_input_variable",
            "hidden_input",
            "module_name",
            "adds_parameter_path",
            "subtracts_parameter_path",
            "enum_values",
            "unit",
            "definition_period",
        ),
        "parameters": ("economy", "household"),
    }
    column_count = sum(len(columns) for columns in added_columns.values())
    assert upgrade.count("op.add_column(") == column_count
    assert upgrade.count("nullable=True") == column_count
    assert downgrade.count("op.drop_column(") == column_count
    for table_name, columns in added_columns.items():
        for column_name in columns:
            assert f'"{column_name}"' in upgrade
            assert f'op.drop_column("{table_name}", "{column_name}")' in downgrade
    for body in (upgrade, downgrade):
        assert "op.execute(" not in body
        assert "op.bulk_insert(" not in body
        assert "server_default" not in body


def test_parameter_tree_revision_creates_only_the_children_table() -> None:
    """The revision after the coordinate removal creates the parameter tree's table.

    It is generated, creates the table with its two listing indexes and its
    parameter index, drops them on downgrade, and writes no data: rows are
    written by catalog publication.
    """
    script = ScriptDirectory.from_config(Config(str(REPO / "alembic-v2.ini")))
    children = [
        revision
        for revision in script.walk_revisions()
        if revision.down_revision == AREA_IMPACT_COORDINATE_REVISION
    ]
    assert len(children) == 1
    assert children[0].revision == PARAMETER_TREE_REVISION
    revision = Path(children[0].path).read_text(encoding="utf-8")
    upgrade = revision[
        revision.index("def upgrade()") : revision.index("def downgrade()")
    ]
    downgrade = revision[revision.index("def downgrade()") :]

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert upgrade.count("op.create_table(") == 1
    assert '"parameter_tree_children"' in upgrade
    assert upgrade.count("op.create_index(") == 3
    assert downgrade.count("op.drop_index(") == 3
    assert downgrade.count("op.drop_table(") == 1
    for index_name in (
        "ix_parameter_tree_children_listing",
        "ix_parameter_tree_children_reform_listing",
        "ix_parameter_tree_children_parameter_id",
    ):
        assert index_name in upgrade
        assert index_name in downgrade
    for body in (upgrade, downgrade):
        assert "op.execute(" not in body
        assert "op.bulk_insert(" not in body
        assert "op.add_column(" not in body


def test_parameter_search_file_revision_creates_only_the_files_table() -> None:
    """The revision after the parameter tree creates the search files' table.

    It is generated, creates the table with its unique version constraint and
    drops it on downgrade, and writes no data: catalog publication writes each
    version's file.
    """
    script = ScriptDirectory.from_config(Config(str(REPO / "alembic-v2.ini")))
    children = [
        revision
        for revision in script.walk_revisions()
        if revision.down_revision == PARAMETER_TREE_REVISION
    ]
    assert len(children) == 1
    assert children[0].revision == PARAMETER_SEARCH_FILE_REVISION
    revision = Path(children[0].path).read_text(encoding="utf-8")
    upgrade = revision[
        revision.index("def upgrade()") : revision.index("def downgrade()")
    ]
    downgrade = revision[revision.index("def downgrade()") :]

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert upgrade.count("op.create_table(") == 1
    assert '"parameter_search_files"' in upgrade
    assert "uq_parameter_search_files_model_version_format" in upgrade
    assert downgrade.count("op.drop_table(") == 1
    assert '"parameter_search_files"' in downgrade
    for body in (upgrade, downgrade):
        assert "op.execute(" not in body
        assert "op.bulk_insert(" not in body
        assert "op.add_column(" not in body


def test_catalog_pruning_revision_adds_only_two_nullable_columns() -> None:
    """The revision after the search file adds the catalog pruning columns.

    It is generated, adds the nullable, timezone-aware
    ``catalog_last_published_at`` and ``catalog_values_pruned_at`` columns to
    ``tax_benefit_model_versions`` and drops them on downgrade, and writes no
    data: catalog publication sets both.
    """
    script = ScriptDirectory.from_config(Config(str(REPO / "alembic-v2.ini")))
    children = [
        revision
        for revision in script.walk_revisions()
        if revision.down_revision == PARAMETER_SEARCH_FILE_REVISION
    ]
    assert len(children) == 1
    assert children[0].revision == CATALOG_PRUNING_REVISION
    revision = Path(children[0].path).read_text(encoding="utf-8")
    upgrade = revision[
        revision.index("def upgrade()") : revision.index("def downgrade()")
    ]
    downgrade = revision[revision.index("def downgrade()") :]

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert upgrade.count("op.add_column(") == 2
    assert upgrade.count('"tax_benefit_model_versions"') == 2
    assert downgrade.count("op.drop_column(") == 2
    for column_name in ("catalog_last_published_at", "catalog_values_pruned_at"):
        assert re.search(
            rf'sa\.Column\(\s*"{column_name}",\s*'
            r"sa\.DateTime\(timezone=True\),\s*nullable=True,?\s*\)",
            upgrade,
        ), column_name
        assert f'"{column_name}"' in downgrade
    for body in (upgrade, downgrade):
        assert "op.execute(" not in body
        assert "op.bulk_insert(" not in body
        assert "op.create_table(" not in body
        assert "op.drop_table(" not in body


def _simulation_runs_revision_source() -> str:
    """Return the source of the one revision after the catalog pruning revision."""
    (path,) = (REPO / "migrations/v2/versions").glob(f"{SIMULATION_RUNS_REVISION}_*.py")
    return path.read_text(encoding="utf-8")


def _user_types_revision_source() -> str:
    """Return the source of the one revision after the simulation runs revision."""
    (path,) = (REPO / "migrations/v2/versions").glob(f"{USER_TYPES_REVISION}_*.py")
    return path.read_text(encoding="utf-8")


def test_user_type_changes_revision_only_adds_the_history_table() -> None:
    """The generated revision after the user types revision adds one table."""
    (path,) = (REPO / "migrations/v2/versions").glob(
        f"{USER_TYPE_CHANGES_REVISION}_*.py"
    )
    revision = path.read_text(encoding="utf-8")
    upgrade = revision[
        revision.index("def upgrade()") : revision.index("def downgrade()")
    ]
    downgrade = revision[revision.index("def downgrade()") :]

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert f'down_revision: Union[str, None] = "{USER_TYPES_REVISION}"' in revision
    assert "correction" not in revision.lower()
    assert sorted(set(re.findall(r"op\.\w+", upgrade))) == [
        "op.create_index",
        "op.create_table",
        "op.f",
    ]
    assert upgrade.count("op.create_table(") == 1
    assert upgrade.count("op.create_index(") == 2
    assert 'op.create_table(\n        "user_type_changes"' in upgrade
    assert sorted(set(re.findall(r"op\.\w+", downgrade))) == [
        "op.drop_index",
        "op.drop_table",
    ]
    assert 'op.drop_table("user_type_changes")' in downgrade


def test_user_types_revision_only_replaces_the_user_type_check() -> None:
    """The generated revision swaps the users type check for one allowing four types.

    Alembic compares check constraints by name only, not by condition, so the
    check that allows author and admin has a new name, which autogenerate turns
    into a drop and an add.
    """
    revision = _user_types_revision_source()
    upgrade = revision[
        revision.index("def upgrade()") : revision.index("def downgrade()")
    ]
    downgrade = revision[revision.index("def downgrade()") :]

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert f'down_revision: Union[str, None] = "{SAVED_ITEM_KEYS_REVISION}"' in revision
    assert "correction" not in revision.lower()
    for body in (upgrade, downgrade):
        assert sorted(re.findall(r"op\.\w+", body)) == [
            "op.create_check_constraint",
            "op.drop_constraint",
            "op.f",
            "op.f",
        ]
    assert re.search(
        r'op\.drop_constraint\(\s*op\.f\("ck_users_user_type"\),\s*"users",'
        r'\s*type_="check"',
        upgrade,
    )
    assert re.search(
        r'op\.create_check_constraint\(\s*op\.f\("ck_users_user_type_allowed"\),'
        r"\s*\"users\",\s*\"user_type IN \('unauthenticated', 'standard', "
        r"'author', 'admin'\)\"",
        upgrade,
    )
    assert re.search(
        r'op\.drop_constraint\(\s*op\.f\("ck_users_user_type_allowed"\),\s*"users",'
        r'\s*type_="check"',
        downgrade,
    )
    # The restored check allows only the two types the parent revision knew.
    restored_check = re.search(
        r'op\.create_check_constraint\(\s*op\.f\("ck_users_user_type"\),'
        r'\s*"users",\s*(".*?")\s*,?\s*\)',
        downgrade,
        flags=re.DOTALL,
    )
    assert restored_check is not None
    assert re.findall(r"'(\w+)'::character varying", restored_check.group(1)) == [
        "unauthenticated",
        "standard",
    ]


def test_simulation_runs_revision_is_generated_with_documented_corrections() -> None:
    """One generated revision follows the catalog pruning revision.

    Its corrections make new columns reuse enum types the baseline created:
    ``simulation_runs.status`` reuses ``simulations.status``'s, and
    ``budget_window_runs.status`` and ``trigger`` reuse the report run's.
    """
    revision = _simulation_runs_revision_source()
    upgrade = revision[
        revision.index("def upgrade()") : revision.index("def downgrade()")
    ]
    downgrade = revision[revision.index("def downgrade()") :]

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert f'down_revision: Union[str, None] = "{CATALOG_PRUNING_REVISION}"' in revision
    assert revision.count("Dialect correction:") == 3
    assert "reversibility correction" not in revision
    for type_name in (
        "v2_simulation_status",
        "v2_report_run_status",
        "v2_report_run_trigger",
    ):
        assert f'name="{type_name}",\n                create_type=False,' in upgrade
    for table_name in (
        "simulation_runs",
        "budget_window_runs",
        "labor_supply_responses",
        "labor_supply_decile_responses",
    ):
        assert f'op.create_table(\n        "{table_name}"' in upgrade
        assert f'op.drop_table("{table_name}")' in downgrade
    assert upgrade.count("op.drop_table(") == 0
    for removed_column in (
        "status",
        "error_message",
        "started_at",
        "completed_at",
        "household_result",
        "output_dataset_id",
    ):
        assert f'op.drop_column("simulations", "{removed_column}")' in upgrade
    for body in (upgrade, downgrade):
        assert "op.execute(" not in body
        assert "op.bulk_insert(" not in body


def test_saved_item_keys_revision_adds_only_two_foreign_keys() -> None:
    """The revision after the simulation runs revision keys saved items.

    It is generated, adds ``RESTRICT`` foreign keys from
    ``user_report_associations.report_id`` to ``reports`` and from
    ``user_simulation_associations.simulation_id`` to ``simulations``, drops
    them on downgrade, and changes nothing else.
    """
    script = ScriptDirectory.from_config(Config(str(REPO / "alembic-v2.ini")))
    children = [
        revision
        for revision in script.walk_revisions()
        if revision.down_revision == SIMULATION_RUNS_REVISION
    ]
    assert len(children) == 1
    assert children[0].revision == SAVED_ITEM_KEYS_REVISION
    revision = Path(children[0].path).read_text(encoding="utf-8")
    upgrade = revision[
        revision.index("def upgrade()") : revision.index("def downgrade()")
    ]
    downgrade = revision[revision.index("def downgrade()") :]

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert upgrade.count("op.create_foreign_key(") == 2
    assert downgrade.count("op.drop_constraint(") == 2
    for key_name, source_table, target_table, column_name in (
        (
            "fk_user_report_associations_report_id_reports",
            "user_report_associations",
            "reports",
            "report_id",
        ),
        (
            "fk_user_simulation_associations_simulation_id_simulations",
            "user_simulation_associations",
            "simulations",
            "simulation_id",
        ),
    ):
        assert re.search(
            rf'op\.create_foreign_key\(\s*op\.f\("{key_name}"\),\s*'
            rf'"{source_table}",\s*"{target_table}",\s*'
            rf'\["{column_name}"\],\s*\["id"\],\s*ondelete="RESTRICT",?\s*\)',
            upgrade,
        ), key_name
        assert f'op.f("{key_name}")' in downgrade
    for body in (upgrade, downgrade):
        assert "op.execute(" not in body
        assert "op.bulk_insert(" not in body
        assert "op.create_table(" not in body
        assert "op.drop_table(" not in body
        assert "op.add_column(" not in body
        assert "op.drop_column(" not in body


def test_spm_availability_revision_adds_only_one_nullable_column() -> None:
    """The revision after the user type changes records SPM availability.

    It is generated, adds the nullable JSON ``spm_availability`` column to
    ``tax_benefit_model_versions`` and drops it on downgrade, and writes no
    data: catalog publication records it.
    """
    script = ScriptDirectory.from_config(Config(str(REPO / "alembic-v2.ini")))
    children = [
        revision
        for revision in script.walk_revisions()
        if revision.down_revision == USER_TYPE_CHANGES_REVISION
    ]
    assert len(children) == 1
    assert children[0].revision == SPM_AVAILABILITY_REVISION
    revision = Path(children[0].path).read_text(encoding="utf-8")
    upgrade = revision[
        revision.index("def upgrade()") : revision.index("def downgrade()")
    ]
    downgrade = revision[revision.index("def downgrade()") :]

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    # The revision stays as Alembic wrote it, in either quote style.
    assert upgrade.count("op.add_column(") == 1
    assert re.search(
        r"""op\.add_column\(\s*["']tax_benefit_model_versions["'],\s*"""
        r"""sa\.Column\(\s*["']spm_availability["'],\s*sa\.JSON\(\),\s*"""
        r"nullable=True,?\s*\),?\s*\)",
        upgrade,
    )
    assert downgrade.count("op.drop_column(") == 1
    assert re.search(
        r"""op\.drop_column\(\s*["']tax_benefit_model_versions["'],\s*"""
        r"""["']spm_availability["'],?\s*\)""",
        downgrade,
    )
    for body in (upgrade, downgrade):
        assert "op.execute(" not in body
        assert "op.bulk_insert(" not in body
        assert "op.create_table(" not in body
        assert "op.drop_table(" not in body


def test_withheld_area_codes_revision_creates_only_the_table_and_its_type() -> None:
    """The revision after SPM availability adds ``withheld_area_codes``.

    It is generated, creates the table with its ``v2_uk_area_type`` enum, and
    writes no data. Its one post-generation correction drops the enum type on
    downgrade, after the table, which Alembic's generated downgrade leaves.
    """
    script = ScriptDirectory.from_config(Config(str(REPO / "alembic-v2.ini")))
    children = [
        revision
        for revision in script.walk_revisions()
        if revision.down_revision == SPM_AVAILABILITY_REVISION
    ]
    assert [child.revision for child in children] == [WITHHELD_AREA_CODES_REVISION]
    revision = Path(children[0].path).read_text(encoding="utf-8")
    upgrade = revision[
        revision.index("def upgrade()") : revision.index("def downgrade()")
    ]
    downgrade = revision[revision.index("def downgrade()") :]

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert sorted(set(re.findall(r"op\.\w+", upgrade))) == [
        "op.create_table",
        "op.f",
    ]
    assert upgrade.count("op.create_table(") == 1
    assert re.search(r"""op\.create_table\(\s*["']withheld_area_codes["']""", upgrade)
    assert re.search(
        r"""sa\.Enum\(\s*["']constituency["'],\s*["']local_authority["'],\s*"""
        r"""name=["']v2_uk_area_type["']""",
        upgrade,
    )
    assert sorted(set(re.findall(r"op\.\w+", downgrade))) == [
        "op.drop_table",
        "op.get_bind",
    ]
    assert re.search(r"""op\.drop_table\(\s*["']withheld_area_codes["']""", downgrade)
    assert revision.count("Post-generation reversibility correction:") == 1
    corrected_enum_names = re.findall(
        r"sa\.Enum\(name=[\"']([^\"']+)[\"']\)\.drop\(op\.get_bind\(\)\)",
        downgrade,
    )
    assert corrected_enum_names == ["v2_uk_area_type"]
    # The type is dropped after the table that uses it.
    assert downgrade.index("drop_table(") < downgrade.index(".drop(op.get_bind())")
    for body in (upgrade, downgrade):
        assert "op.execute(" not in body
        assert "op.bulk_insert(" not in body


def test_shared_reports_revision_is_generated_with_one_documented_correction() -> None:
    """The shared reports revision lets identical requests share reports and runs.

    It is generated on the withheld area codes revision, with one correction:
    ``user_report_run_associations.trigger`` reuses the report runs'
    ``v2_report_run_trigger`` type. It creates only that table, writes no
    data, makes three per-user columns nullable (the integration shape test
    checks the direction), and its downgrade reverses what the upgrade does.
    """
    script = ScriptDirectory.from_config(Config(str(REPO / "alembic-v2.ini")))
    children = [
        revision
        for revision in script.walk_revisions()
        if revision.down_revision == WITHHELD_AREA_CODES_REVISION
    ]
    assert len(children) == 1
    assert children[0].revision == SHARED_REPORTS_REVISION
    revision = Path(children[0].path).read_text(encoding="utf-8")
    upgrade = revision[
        revision.index("def upgrade()") : revision.index("def downgrade()")
    ]
    downgrade = revision[revision.index("def downgrade()") :]

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert revision.count("Dialect correction:") == 1
    assert re.search(
        r"""name=["']v2_report_run_trigger["'],\s*create_type=False""", upgrade
    )
    assert re.findall(r"""op\.create_table\(\s*["'](\w+)["']""", upgrade) == [
        "user_report_run_associations"
    ]
    assert re.findall(r"""op\.drop_table\(\s*["'](\w+)["']""", downgrade) == [
        "user_report_run_associations"
    ]
    assert upgrade.count("op.add_column(") == downgrade.count("op.drop_column(") == 8
    # The per-user columns of shared rows become nullable, and back.
    for body in (upgrade, downgrade):
        assert sorted(
            re.findall(r"""op\.alter_column\(\s*["'](\w+)["'],\s*["'](\w+)["']""", body)
        ) == [
            ("budget_window_runs", "trigger"),
            ("report_runs", "trigger"),
            ("reports", "label"),
        ]
        assert "op.execute(" not in body
        assert "op.bulk_insert(" not in body
    assert "op.drop_column(" not in upgrade
    assert "op.drop_table(" not in upgrade


def test_user_invitations_revision_adds_its_table_and_the_dismissal_column() -> None:
    """The revision after shared reports adds invitations and dismissals.

    It is generated with no corrections: it adds ``user_invitations`` with
    its two indexes, adds ``user_type_changes.dismissed_at``, and replaces
    the source check with one that also allows ``invitation``, under a new
    name because Alembic compares checks by name only. The downgrade undoes
    each, and neither writes data.
    """
    (path,) = (REPO / "migrations/v2/versions").glob(
        f"{USER_INVITATIONS_REVISION}_*.py"
    )
    revision = path.read_text(encoding="utf-8")
    upgrade = revision[
        revision.index("def upgrade()") : revision.index("def downgrade()")
    ]
    downgrade = revision[revision.index("def downgrade()") :]

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert f'down_revision: Union[str, None] = "{SHARED_REPORTS_REVISION}"' in revision
    assert "correction" not in revision.lower()
    assert sorted(re.findall(r"op\.\w+", upgrade)) == [
        "op.add_column",
        "op.create_check_constraint",
        "op.create_index",
        "op.create_index",
        "op.create_table",
        "op.drop_constraint",
        # Five constraint names in create_table, and the two checks'.
        *["op.f"] * 7,
    ]
    assert sorted(re.findall(r"op\.\w+", downgrade)) == [
        "op.create_check_constraint",
        "op.drop_column",
        "op.drop_constraint",
        "op.drop_index",
        "op.drop_index",
        "op.drop_table",
        "op.f",
        "op.f",
    ]
    assert re.search(r"op\.create_table\(\s*\"user_invitations\"", upgrade)
    assert re.search(
        r"op\.add_column\(\s*\"user_type_changes\",\s*"
        r"sa\.Column\(\"dismissed_at\", sa\.DateTime\(timezone=True\), "
        r"nullable=True\)",
        upgrade,
    )
    assert "ck_user_type_changes_source_allowed" in upgrade
    assert "source IN ('admin_route', 'script', 'invitation')" in upgrade


def test_dynamics_revision_stores_dynamics_like_policies_and_maps_them() -> None:
    """The revision after user invitations stores dynamics as policies are stored.

    It is generated with no corrections: ``dynamics`` gains policies' five
    columns, their two indexes, two unique constraints, three foreign keys
    and two checks, and loses ``name`` and ``description``;
    ``legacy_policy_mappings`` gains ``dynamic_id`` with its index and key;
    ``parameter_values`` gains the partial unique index on dynamics' values.
    The downgrade undoes each, and neither writes data.
    """
    (path,) = (REPO / "migrations/v2/versions").glob(f"{DYNAMICS_REVISION}_*.py")
    revision = path.read_text(encoding="utf-8")
    upgrade = revision[
        revision.index("def upgrade()") : revision.index("def downgrade()")
    ]
    downgrade = revision[revision.index("def downgrade()") :]

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert (
        f'down_revision: Union[str, None] = "{USER_INVITATIONS_REVISION}"' in revision
    )
    assert "correction" not in revision.lower()
    assert sorted(re.findall(r"op\.\w+", upgrade)) == sorted(
        [
            *["op.add_column"] * 6,
            *["op.create_index"] * 4,
            *["op.create_unique_constraint"] * 2,
            *["op.create_foreign_key"] * 4,
            *["op.create_check_constraint"] * 2,
            *["op.drop_column"] * 2,
            # Two generated index names, three key names and two check names.
            *["op.f"] * 7,
        ]
    )
    assert sorted(re.findall(r"op\.\w+", downgrade)) == sorted(
        [
            *["op.drop_index"] * 4,
            *["op.drop_constraint"] * 8,
            *["op.drop_column"] * 6,
            *["op.add_column"] * 2,
            *["op.f"] * 7,
        ]
    )
    for column_name in (
        "country_id",
        "tax_benefit_model_id",
        "tax_benefit_model_version_id",
        "canonicalization_version",
        "content_hash",
    ):
        assert re.search(
            rf'op\.add_column\(\s*"dynamics",\s*sa\.Column\(\s*"{column_name}",'
            r"[^)]*\)?[^)]*nullable=False",
            upgrade,
        )
    assert re.search(r'op\.drop_column\("dynamics", "name"\)', upgrade)
    assert re.search(r'op\.drop_column\("dynamics", "description"\)', upgrade)
    assert re.search(
        r'op\.add_column\(\s*"legacy_policy_mappings",\s*'
        r'sa\.Column\("dynamic_id", sa\.Uuid\(\), nullable=True\)',
        upgrade,
    )
    assert "fk_legacy_policy_mappings_dynamic_country" in upgrade
    assert "uq_parameter_values_dynamic_parameter_start_date" in upgrade
    assert 'postgresql_where=sa.text("dynamic_id IS NOT NULL")' in upgrade
    assert "op.execute(" not in revision
    assert "op.bulk_insert(" not in revision


def test_cliff_impacts_revision_creates_only_its_table_with_one_correction() -> None:
    """The revision after dynamics adds ``cliff_impacts``.

    It is generated, creates the table with its two indexes and its partial
    unique index, and writes no data. Its one post-generation correction makes
    ``status`` reuse the ``v2_simulation_status`` type the baseline created,
    which the generated ``create_table`` would create again and fail on; so
    the downgrade, which drops only the table, leaves the type to
    ``simulation_runs``.
    """
    (path,) = (REPO / "migrations/v2/versions").glob(f"{CLIFF_IMPACTS_REVISION}_*.py")
    revision = path.read_text(encoding="utf-8")
    upgrade = revision[
        revision.index("def upgrade()") : revision.index("def downgrade()")
    ]
    downgrade = revision[revision.index("def downgrade()") :]

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert re.search(
        rf"""down_revision: Union\[str, None\] = ["']{DYNAMICS_REVISION}["']""",
        revision,
    )
    assert revision.count("Dialect correction:") == 1
    assert re.search(
        r"""name=["']v2_simulation_status["'],\s*create_type=False""", upgrade
    )
    assert re.findall(r"""op\.create_table\(\s*["'](\w+)["']""", upgrade) == [
        "cliff_impacts"
    ]
    assert sorted(
        re.findall(r"""op\.create_index\(\s*(?:op\.f\()?["'](\w+)["']""", upgrade)
    ) == [
        "ix_cliff_impacts_simulation_run_id",
        "ix_cliff_impacts_status_started_at",
        "uq_cliff_impacts_unfailed",
    ]
    assert re.search(
        r"""postgresql_where=sa\.text\(["']status <> 'failed'["']\)""", upgrade
    )
    assert re.findall(r"""op\.drop_table\(\s*["'](\w+)["']""", downgrade) == [
        "cliff_impacts"
    ]
    for body in (upgrade, downgrade):
        assert "op.execute(" not in body
        assert "op.bulk_insert(" not in body
        assert ".drop(op.get_bind())" not in body
    assert "op.alter_column(" not in upgrade
    assert "op.add_column(" not in upgrade


def test_report_column_drops_revision_drops_only_the_named_columns() -> None:
    """The revision after cliff impacts drops what shared report rows don't hold.

    It is generated, removes the nine columns with the key, index and check
    that depend on them, writes no data, and its downgrade adds the columns
    back, empty.
    """
    (path,) = (REPO / "migrations/v2/versions").glob(
        f"{REPORT_COLUMN_DROPS_REVISION}_*.py"
    )
    revision = path.read_text(encoding="utf-8")
    upgrade = revision[
        revision.index("def upgrade()") : revision.index("def downgrade()")
    ]
    downgrade = revision[revision.index("def downgrade()") :]
    dropped_columns = [
        ("budget_window_runs", "trigger"),
        ("report_runs", "baseline_cliff_gap"),
        ("report_runs", "baseline_cliff_share"),
        ("report_runs", "reform_cliff_gap"),
        ("report_runs", "reform_cliff_share"),
        ("report_runs", "trigger"),
        ("reports", "description"),
        ("reports", "label"),
        ("reports", "user_id"),
    ]

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert re.search(
        rf"""down_revision: Union\[str, None\] = ["']{CLIFF_IMPACTS_REVISION}["']""",
        revision,
    )
    drop_column_call = r"""op\.drop_column\(\s*["'](\w+)["'],\s*["'](\w+)["']"""
    add_column_call = (
        r"""op\.add_column\(\s*["'](\w+)["'],\s*sa\.Column\(\s*["'](\w+)["']"""
    )
    assert sorted(re.findall(drop_column_call, upgrade)) == dropped_columns
    assert sorted(re.findall(add_column_call, downgrade)) == dropped_columns
    # The one correction restores the parentheses autogenerate strips.
    assert revision.count("Post-generation correction:") == 1
    assert (
        "'(baseline_cliff_gap IS NULL) = (baseline_cliff_share IS NULL) "
        "AND (baseline_cliff_gap IS NULL) = (reform_cliff_gap IS NULL) "
        "AND (baseline_cliff_gap IS NULL) = (reform_cliff_share IS NULL)'"
    ) in downgrade
    assert "ix_reports_user_id" in upgrade
    assert "fk_reports_user_id_users" in upgrade
    assert "ck_report_runs_cliff_impact_complete" in upgrade
    for body in (upgrade, downgrade):
        assert "op.execute(" not in body
        assert "op.bulk_insert(" not in body
        assert "op.drop_table(" not in body


def test_user_dynamics_revision_creates_only_the_saved_dynamics_table() -> None:
    """The revision after report column drops creates ``user_dynamics`` alone.

    It is generated with no corrections, with its ID chosen through
    ``--rev-id``: one table, whose keys name its user (``CASCADE``), its
    country and a dynamic of that country (both ``RESTRICT``), with its
    three indexes. The downgrade drops them, and neither writes data.
    """
    (path,) = (REPO / "migrations/v2/versions").glob(f"{USER_DYNAMICS_REVISION}_*.py")
    revision = path.read_text(encoding="utf-8")
    upgrade = revision[
        revision.index("def upgrade()") : revision.index("def downgrade()")
    ]
    downgrade = revision[revision.index("def downgrade()") :]

    assert V2_ALEMBIC_HEAD_REVISION == USER_DYNAMICS_REVISION
    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert (
        f'down_revision: Union[str, None] = "{REPORT_COLUMN_DROPS_REVISION}"'
        in revision
    )
    assert "correction" not in revision.lower()
    operations = [name for name in re.findall(r"op\.\w+", upgrade) if name != "op.f"]
    assert sorted(operations) == ["op.create_index"] * 3 + ["op.create_table"]
    reversals = [name for name in re.findall(r"op\.\w+", downgrade) if name != "op.f"]
    assert sorted(reversals) == ["op.drop_index"] * 3 + ["op.drop_table"]
    assert re.search(r'op\.create_table\(\s*"user_dynamics"', upgrade)
    assert 'op.drop_table("user_dynamics")' in downgrade
    for constraint_name in (
        "fk_user_dynamics_dynamic_country",
        "uq_user_dynamics_id_country",
        "ix_user_dynamics_country_user_created_id",
        "ix_user_dynamics_country_dynamic",
    ):
        assert constraint_name in upgrade
    assert re.search(
        r'\["dynamic_id", "country_id"\],\s*\["dynamics\.id", "dynamics\.country_id"\]',
        upgrade,
    )
    assert upgrade.count('ondelete="RESTRICT"') == 2
    assert upgrade.count('ondelete="CASCADE"') == 1
    assert "op.execute(" not in revision
    assert "op.bulk_insert(" not in revision
