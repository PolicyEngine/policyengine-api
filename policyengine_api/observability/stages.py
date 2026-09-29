"""Canonical stage registry for API calculation configurations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


class RunConfiguration(StrEnum):
    HOUSEHOLD = "household"
    ECONOMY_ANNUAL = "economy_annual"
    ECONOMY_BUDGET_WINDOW = "economy_budget_window"


class Stage(StrEnum):
    HOUSEHOLD_LOAD_INPUTS = "household.load_inputs"
    HOUSEHOLD_CACHE_LOOKUP = "household.cache_lookup"
    HOUSEHOLD_INPUT_NORMALIZATION = "household.input_normalization"
    HOUSEHOLD_CALCULATION = "household.calculation"
    HOUSEHOLD_CACHE_WRITE = "household.cache_write"

    ECONOMY_REQUEST = "economy.request"
    ECONOMY_BUDGET_WINDOW_REQUEST = "economy.budget_window_request"
    ECONOMY_LOAD_POLICIES = "economy.load_policies"
    ECONOMY_RESOLVE_CACHED_OR_NEW = "economy.resolve_cached_or_new_impact"
    ECONOMY_RESOLVE_RUNTIME_BUNDLE = "economy.resolve_runtime_bundle"
    ECONOMY_SUBMIT = "economy.submit_impact"
    ECONOMY_START_BUDGET_WINDOW = "economy.start_budget_window_batch"
    ECONOMY_POLL_BUDGET_WINDOW = "economy.poll_budget_window_batch"
    ECONOMY_HANDLE_EXECUTION_STATE = "economy.handle_execution_state"
    ECONOMY_READ_COMPLETED = "economy.read_completed_impact"
    ECONOMY_READ_FAILED = "economy.read_failed_impact"
    ECONOMY_POLL_ACTIVE = "economy.poll_active_impact"
    ECONOMY_PERSIST_COMPUTING = "economy.persist_computing_impact"
    ECONOMY_PERSIST_COMPLETED = "economy.persist_completed_impact"
    ECONOMY_PERSIST_FAILED = "economy.persist_failed_impact"


@dataclass(frozen=True)
class StagePlan:
    configuration: RunConfiguration
    stages: tuple[Stage, ...]

    def name(self, stage: Stage) -> str:
        if stage not in self.stages:
            raise ValueError(
                f"{stage.value!r} is not registered for {self.configuration.value!r}"
            )
        return stage.value


_ECONOMY_COMMON = (
    Stage.ECONOMY_LOAD_POLICIES,
    Stage.ECONOMY_RESOLVE_CACHED_OR_NEW,
    Stage.ECONOMY_RESOLVE_RUNTIME_BUNDLE,
    Stage.ECONOMY_HANDLE_EXECUTION_STATE,
    Stage.ECONOMY_READ_COMPLETED,
    Stage.ECONOMY_READ_FAILED,
    Stage.ECONOMY_POLL_ACTIVE,
    Stage.ECONOMY_PERSIST_COMPUTING,
    Stage.ECONOMY_PERSIST_COMPLETED,
    Stage.ECONOMY_PERSIST_FAILED,
)

RUN_STAGE_REGISTRY: Mapping[RunConfiguration, StagePlan] = MappingProxyType(
    {
        RunConfiguration.HOUSEHOLD: StagePlan(
            RunConfiguration.HOUSEHOLD,
            (
                Stage.HOUSEHOLD_LOAD_INPUTS,
                Stage.HOUSEHOLD_CACHE_LOOKUP,
                Stage.HOUSEHOLD_INPUT_NORMALIZATION,
                Stage.HOUSEHOLD_CALCULATION,
                Stage.HOUSEHOLD_CACHE_WRITE,
            ),
        ),
        RunConfiguration.ECONOMY_ANNUAL: StagePlan(
            RunConfiguration.ECONOMY_ANNUAL,
            (
                Stage.ECONOMY_REQUEST,
                *_ECONOMY_COMMON,
                Stage.ECONOMY_SUBMIT,
            ),
        ),
        RunConfiguration.ECONOMY_BUDGET_WINDOW: StagePlan(
            RunConfiguration.ECONOMY_BUDGET_WINDOW,
            (
                Stage.ECONOMY_BUDGET_WINDOW_REQUEST,
                *_ECONOMY_COMMON,
                Stage.ECONOMY_START_BUDGET_WINDOW,
                Stage.ECONOMY_POLL_BUDGET_WINDOW,
            ),
        ),
    }
)

HOUSEHOLD_STAGES = RUN_STAGE_REGISTRY[RunConfiguration.HOUSEHOLD]
ECONOMY_ANNUAL_STAGES = RUN_STAGE_REGISTRY[RunConfiguration.ECONOMY_ANNUAL]
ECONOMY_BUDGET_WINDOW_STAGES = RUN_STAGE_REGISTRY[
    RunConfiguration.ECONOMY_BUDGET_WINDOW
]
