"""Declarative mappings for the existing API v1 schema.

These mappings describe the legacy tables; importing this module never emits
DDL. Alembic is the only schema-management entrypoint.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class V1Base(DeclarativeBase):
    pass


class Household(V1Base):
    __tablename__ = "household"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[str] = mapped_column(String(3))
    label: Mapped[str | None] = mapped_column(String(255))
    api_version: Mapped[str] = mapped_column(String(255))
    household_json: Mapped[Any] = mapped_column(JSON)
    household_hash: Mapped[str] = mapped_column(String(255))


class ComputedHousehold(V1Base):
    __tablename__ = "computed_household"
    household_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    country_id: Mapped[str] = mapped_column(String(3), primary_key=True)
    api_version: Mapped[str] = mapped_column(String(10))
    computed_household_json: Mapped[Any] = mapped_column(JSON)
    status: Mapped[str | None] = mapped_column(String(32))


class Policy(V1Base):
    __tablename__ = "policy"
    # SQLite cannot compile AUTO_INCREMENT on a composite primary key. The
    # generated MySQL baseline receives the documented dialect correction.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    country_id: Mapped[str] = mapped_column(String(3), primary_key=True)
    label: Mapped[str | None] = mapped_column(String(255))
    api_version: Mapped[str] = mapped_column(String(10))
    policy_json: Mapped[Any] = mapped_column(JSON)
    policy_hash: Mapped[str] = mapped_column(String(255), primary_key=True)


class Economy(V1Base):
    __tablename__ = "economy"
    economy_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    policy_id: Mapped[int]
    country_id: Mapped[str] = mapped_column(String(3))
    region: Mapped[str | None] = mapped_column(String(32))
    time_period: Mapped[str | None] = mapped_column(String(32))
    options_json: Mapped[Any] = mapped_column(JSON)
    options_hash: Mapped[str] = mapped_column(String(255))
    api_version: Mapped[str] = mapped_column(String(10))
    economy_json: Mapped[Any | None] = mapped_column(JSON(none_as_null=True))
    status: Mapped[str] = mapped_column(String(32))
    message: Mapped[str | None] = mapped_column(String(255))


class ReformImpact(V1Base):
    __tablename__ = "reform_impact"
    reform_impact_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    baseline_policy_id: Mapped[int]
    reform_policy_id: Mapped[int]
    country_id: Mapped[str] = mapped_column(String(3))
    region: Mapped[str] = mapped_column(String(32))
    dataset: Mapped[str] = mapped_column(String(255))
    time_period: Mapped[str] = mapped_column(String(32))
    options_json: Mapped[Any | None] = mapped_column(JSON(none_as_null=True))
    options_hash: Mapped[str | None] = mapped_column(String(255))
    api_version: Mapped[str] = mapped_column(String(10))
    reform_impact_json: Mapped[Any] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32))
    message: Mapped[str | None] = mapped_column(String(255))
    start_time: Mapped[datetime | None] = mapped_column(DateTime)
    end_time: Mapped[datetime | None] = mapped_column(DateTime)
    execution_id: Mapped[str] = mapped_column(String(255))


class Analysis(V1Base):
    __tablename__ = "analysis"
    prompt_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    prompt: Mapped[str] = mapped_column(Text)
    analysis: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))


class UserPolicy(V1Base):
    __tablename__ = "user_policies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[str] = mapped_column(String(3))
    reform_id: Mapped[int]
    reform_label: Mapped[str | None] = mapped_column(String(255))
    baseline_id: Mapped[int]
    baseline_label: Mapped[str | None] = mapped_column(String(255))
    user_id: Mapped[str] = mapped_column(String(255))
    year: Mapped[str] = mapped_column(String(32))
    geography: Mapped[str] = mapped_column(String(255))
    dataset: Mapped[str | None] = mapped_column(String(255))
    number_of_provisions: Mapped[int]
    api_version: Mapped[str] = mapped_column(String(32))
    added_date: Mapped[int] = mapped_column(BigInteger)
    updated_date: Mapped[int] = mapped_column(BigInteger)
    budgetary_impact: Mapped[str | None] = mapped_column(String(255))
    type: Mapped[str | None] = mapped_column(String(255))


class UserProfile(V1Base):
    __tablename__ = "user_profiles"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    auth0_id: Mapped[str] = mapped_column(String(255), unique=True)
    username: Mapped[str | None] = mapped_column(String(255), unique=True)
    primary_country: Mapped[str] = mapped_column(String(3))
    user_since: Mapped[int] = mapped_column(BigInteger)


class Tracer(V1Base):
    __tablename__ = "tracers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    household_id: Mapped[int]
    policy_id: Mapped[int]
    country_id: Mapped[str] = mapped_column(String(3))
    api_version: Mapped[str] = mapped_column(String(10))
    tracer_output: Mapped[Any] = mapped_column(JSON)


class Simulation(V1Base):
    __tablename__ = "simulations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[str] = mapped_column(String(3))
    api_version: Mapped[str] = mapped_column(String(10))
    population_id: Mapped[str] = mapped_column(String(255))
    population_type: Mapped[str] = mapped_column(String(50))
    policy_id: Mapped[int]
    status: Mapped[str] = mapped_column(String(32), server_default=text("'pending'"))
    output: Mapped[Any | None] = mapped_column(JSON(none_as_null=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    simulation_spec_json: Mapped[Any | None] = mapped_column(JSON(none_as_null=True))
    simulation_spec_schema_version: Mapped[int | None]
    active_run_id: Mapped[str | None] = mapped_column(String(36))
    latest_successful_run_id: Mapped[str | None] = mapped_column(String(36))


class ReportOutput(V1Base):
    __tablename__ = "report_outputs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[str] = mapped_column(String(3))
    simulation_1_id: Mapped[int]
    simulation_2_id: Mapped[int | None]
    api_version: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(32), server_default=text("'pending'"))
    output: Mapped[Any | None] = mapped_column(JSON(none_as_null=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    year: Mapped[str | None] = mapped_column(String(255), server_default=text("'2025'"))
    report_kind: Mapped[str | None] = mapped_column(String(64))
    report_spec_json: Mapped[Any | None] = mapped_column(JSON(none_as_null=True))
    report_spec_schema_version: Mapped[int | None]
    report_spec_status: Mapped[str | None] = mapped_column(String(32))
    active_run_id: Mapped[str | None] = mapped_column(String(36))
    latest_successful_run_id: Mapped[str | None] = mapped_column(String(36))


class ReportOutputRun(V1Base):
    __tablename__ = "report_output_runs"
    __table_args__ = (UniqueConstraint("report_output_id", "run_sequence"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    report_output_id: Mapped[int]
    run_sequence: Mapped[int]
    status: Mapped[str] = mapped_column(String(32))
    output: Mapped[Any | None] = mapped_column(JSON(none_as_null=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    trigger_type: Mapped[str] = mapped_column(String(32))
    requested_at: Mapped[datetime | None] = mapped_column(DateTime)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_run_id: Mapped[str | None] = mapped_column(String(36))
    report_spec_snapshot_json: Mapped[Any | None] = mapped_column(
        JSON(none_as_null=True)
    )
    country_package_version: Mapped[str | None] = mapped_column(String(255))
    policyengine_version: Mapped[str | None] = mapped_column(String(255))
    data_version: Mapped[str | None] = mapped_column(String(255))
    runtime_app_name: Mapped[str | None] = mapped_column(String(255))
    report_cache_version: Mapped[str | None] = mapped_column(String(255))
    simulation_cache_version: Mapped[str | None] = mapped_column(String(255))
    requested_version_override: Mapped[str | None] = mapped_column(String(255))
    resolved_dataset: Mapped[str | None] = mapped_column(String(255))
    resolved_options_hash: Mapped[str | None] = mapped_column(String(255))


class SimulationRun(V1Base):
    __tablename__ = "simulation_runs"
    __table_args__ = (UniqueConstraint("simulation_id", "run_sequence"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    simulation_id: Mapped[int]
    report_output_run_id: Mapped[str | None] = mapped_column(String(36))
    input_position: Mapped[int | None]
    run_sequence: Mapped[int]
    status: Mapped[str] = mapped_column(String(32))
    output: Mapped[Any | None] = mapped_column(JSON(none_as_null=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    trigger_type: Mapped[str] = mapped_column(String(32))
    requested_at: Mapped[datetime | None] = mapped_column(DateTime)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_run_id: Mapped[str | None] = mapped_column(String(36))
    simulation_spec_snapshot_json: Mapped[Any | None] = mapped_column(
        JSON(none_as_null=True)
    )
    country_package_version: Mapped[str | None] = mapped_column(String(255))
    policyengine_version: Mapped[str | None] = mapped_column(String(255))
    data_version: Mapped[str | None] = mapped_column(String(255))
    runtime_app_name: Mapped[str | None] = mapped_column(String(255))
    simulation_cache_version: Mapped[str | None] = mapped_column(String(255))


class LegacyReportOutputAlias(V1Base):
    __tablename__ = "legacy_report_output_aliases"
    legacy_report_output_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_report_output_id: Mapped[int]
