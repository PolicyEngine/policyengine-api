"""Unit checks of the dynamics revisions of the v2 Alembic chain.

The revisions that store dynamics like policies (9d1d12a7ac58), store users'
saved dynamics (d417fe8b1b17), move dynamic parameters and their values into
their own tables (7f7335f0eb31) and drop ``parameter_values.dynamic_id``
(1c651058fac5). As in ``test_alembic_v2_revisions``, where the chain's order
is checked, these tests read the revision files and check the operations
each one runs.
"""

import importlib.util
import re
from pathlib import Path

from policyengine_api.constants import REPO
from policyengine_api.dynamic_parameters import DYNAMIC_PARAMETER_PREFIXES
from tests.unit.v2.test_alembic_v2_revisions import (
    DYNAMIC_PARAMETER_TABLES_REVISION,
    DYNAMICS_REVISION,
    PARAMETER_VALUES_DYNAMIC_ID_DROP_REVISION,
    REPORT_COLUMN_DROPS_REVISION,
    USER_DYNAMICS_REVISION,
    USER_INVITATIONS_REVISION,
)


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


def _dynamic_parameter_tables_revision_path() -> Path:
    (path,) = (REPO / "migrations/v2/versions").glob(
        f"{DYNAMIC_PARAMETER_TABLES_REVISION}_*.py"
    )
    return path


def test_dynamic_parameter_tables_revision_creates_two_tables_and_moves_rows() -> None:
    """The revision after user dynamics adds the two tables, then moves rows.

    Its tables and indexes are generated. Its one data step is the user's
    migration decision (C1 · 46, Q2), written by hand: after the generated
    tables are created it moves every stored dynamic parameter and value into
    them, and before the generated drops its downgrade moves them back. It has
    no other correction.
    """
    revision = _dynamic_parameter_tables_revision_path().read_text(encoding="utf-8")
    upgrade = revision[
        revision.index("def upgrade()") : revision.index("def downgrade()")
    ]
    downgrade = revision[revision.index("def downgrade()") :]
    parent = USER_DYNAMICS_REVISION

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert re.search(
        rf"""down_revision: Union\[str, None\] = ["']{parent}["']""", revision
    )
    assert "C1 · 46" in revision
    assert "Q2" in revision
    assert re.findall(r"""op\.create_table\(\s*["'](\w+)["']""", upgrade) == [
        "dynamic_parameters",
        "dynamic_parameter_values",
    ]
    assert sorted(
        re.findall(r"""op\.create_index\(\s*(?:op\.f\()?["'](\w+)["']""", upgrade)
    ) == [
        "ix_dynamic_parameter_values_parameter_period",
        "ix_dynamic_parameters_tax_benefit_model_version_id",
        "uq_dynamic_parameter_values_current_law_parameter_start_date",
        "uq_dynamic_parameter_values_dynamic_parameter_start_date",
    ]
    assert sorted(re.findall(r"""op\.drop_table\(\s*["'](\w+)["']""", downgrade)) == [
        "dynamic_parameter_values",
        "dynamic_parameters",
    ]
    assert revision.count("Approved hand-written data step") == 2
    assert "Post-generation correction" not in revision
    assert "op.bulk_insert(" not in revision
    move = upgrade.index("_move_dynamic_parameters_into_their_tables()")
    assert upgrade.rindex("op.create_index(") < move
    move_back = downgrade.index("_move_dynamic_parameters_back()")
    assert move_back < downgrade.index("op.drop_index(")
    for table in ("parameters", "parameter_values", "parameter_tree_children"):
        assert f'op.drop_table("{table}")' not in revision


def test_dynamic_parameter_tables_revision_keeps_its_own_copy_of_the_prefixes() -> None:
    """The revision classifies with a frozen copy that matches the package's.

    A revision runs once per database, so it never imports application code
    that may change; publication compares the installed version's rows with
    the package's own classification right after it.
    """
    path = _dynamic_parameter_tables_revision_path()
    source = path.read_text(encoding="utf-8")
    spec = importlib.util.spec_from_file_location("dynamic_parameter_tables", path)
    assert spec is not None
    assert spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)

    assert "policyengine_api" not in source
    package_prefixes = dict(DYNAMIC_PARAMETER_PREFIXES)
    assert package_prefixes == revision.DYNAMIC_PARAMETER_PREFIXES


def test_parameter_values_dynamic_id_drop_is_generated_with_no_corrections() -> None:
    """The revision after the dynamic parameter tables drops what dynamics used.

    It is generated, with its ID chosen through ``--rev-id``, after
    ``ParameterValue`` lost ``dynamic_id``, its single-owner check and its
    per-dynamic index, and the current-law index was renamed, since Alembic
    compares an index's condition by name only. PostgreSQL drops an index
    whose condition names a dropped column, so the upgrade creates the renamed
    index with ``policy_id IS NULL`` and the downgrade restores the old one.
    Neither writes data, and there is no hand-written step: an operator counts
    the rows that still name a dynamic before the merge (C1 · 53, decision 3).
    """
    (path,) = (REPO / "migrations/v2/versions").glob(
        f"{PARAMETER_VALUES_DYNAMIC_ID_DROP_REVISION}_*.py"
    )
    revision = path.read_text(encoding="utf-8")
    upgrade = revision[
        revision.index("def upgrade()") : revision.index("def downgrade()")
    ]
    downgrade = revision[revision.index("def downgrade()") :]
    index_name = r"""(?:op\.f\()?["'](\w+)["']"""

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    parent = DYNAMIC_PARAMETER_TABLES_REVISION
    assert re.search(
        rf"""down_revision: Union\[str, None\] = ["']{parent}["']""", revision
    )
    assert "correction" not in revision.lower()
    operations = [name for name in re.findall(r"op\.\w+", upgrade) if name != "op.f"]
    assert sorted(operations) == [
        "op.create_index",
        "op.drop_column",
        "op.drop_constraint",
        "op.drop_constraint",
        "op.drop_index",
        "op.drop_index",
    ]
    reversals = [name for name in re.findall(r"op\.\w+", downgrade) if name != "op.f"]
    assert sorted(reversals) == [
        "op.add_column",
        "op.create_check_constraint",
        "op.create_foreign_key",
        "op.create_index",
        "op.create_index",
        "op.drop_index",
    ]
    assert re.findall(
        rf"op\.drop_column\(\s*{index_name},\s*{index_name}", upgrade
    ) == [("parameter_values", "dynamic_id")]
    assert sorted(re.findall(rf"op\.drop_index\(\s*{index_name}", upgrade)) == [
        "uq_parameter_values_canonical_parameter_start_date",
        "uq_parameter_values_dynamic_parameter_start_date",
    ]
    assert re.findall(rf"op\.create_index\(\s*{index_name}", upgrade) == [
        "uq_parameter_values_current_law_parameter_start_date"
    ]
    for dialect in ("postgresql", "sqlite"):
        assert re.search(
            rf"""{dialect}_where=sa\.text\(["']policy_id IS NULL["']\)""", upgrade
        )
    assert "fk_parameter_values_dynamic_id_dynamics" in upgrade
    assert "ck_parameter_values_single_owner" in upgrade
    # The column comes back first, so the restored key, check and indexes can
    # name it.
    assert downgrade.index("op.add_column(") < downgrade.index(
        "op.create_check_constraint("
    )
    assert sorted(re.findall(rf"op\.create_index\(\s*{index_name}", downgrade)) == [
        "uq_parameter_values_canonical_parameter_start_date",
        "uq_parameter_values_dynamic_parameter_start_date",
    ]
    for body in (upgrade, downgrade):
        assert "op.execute(" not in body
        assert "op.bulk_insert(" not in body
        assert "op.drop_table(" not in body
