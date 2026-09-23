import pytest

from policyengine_api.observability.stages import (
    RUN_STAGE_REGISTRY,
    RunConfiguration,
    Stage,
)


def test_registry_defines_every_run_configuration_and_stage() -> None:
    assert set(RUN_STAGE_REGISTRY) == set(RunConfiguration)
    registered = {
        stage
        for stage_plan in RUN_STAGE_REGISTRY.values()
        for stage in stage_plan.stages
    }
    assert registered == set(Stage)


@pytest.mark.parametrize("stage_plan", RUN_STAGE_REGISTRY.values())
def test_each_stage_plan_is_ordered_and_contains_no_duplicates(stage_plan) -> None:
    assert stage_plan.stages
    assert len(stage_plan.stages) == len(set(stage_plan.stages))
    assert all(stage_plan.name(stage) == stage.value for stage in stage_plan.stages)


def test_stage_plan_rejects_a_stage_from_another_configuration() -> None:
    household = RUN_STAGE_REGISTRY[RunConfiguration.HOUSEHOLD]

    with pytest.raises(ValueError, match="not registered"):
        household.name(Stage.ECONOMY_SUBMIT)
