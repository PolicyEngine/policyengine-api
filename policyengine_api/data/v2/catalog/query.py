"""Read-only v2 catalog queries and deterministic response serialization."""

from __future__ import annotations

from collections import defaultdict

from packaging.version import InvalidVersion, Version
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from policyengine_api.data.v2.catalog.schemas import (
    MetadataDataset,
    MetadataDatasetOption,
    MetadataEconomyOptions,
    MetadataModel,
    MetadataModelVersion,
    MetadataParameter,
    MetadataParameterNode,
    MetadataParameterValue,
    MetadataRegion,
    MetadataRegionOption,
    MetadataResult,
    MetadataTimePeriodOption,
    MetadataVariable,
)
from policyengine_api.data.v2.models import (
    Dataset,
    Parameter,
    ParameterNode,
    ParameterValue,
    Region,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    Variable,
)


SUPPORTED_PREVIEW_COUNTRIES = frozenset({"us", "uk"})


class MetadataCatalogUnavailableError(RuntimeError):
    """Raised when a complete initialized catalog cannot be read."""


class UnsupportedPreviewCountryError(ValueError):
    """Raised when a country has no Stage 9 preview catalog."""


class InvalidPolicyEngineVersionError(ValueError):
    """Raised when an explicit version is not a canonical package version."""


class MetadataCatalogVersionNotFoundError(LookupError):
    """Raised when an explicitly selected catalog version is absent."""


def validate_policyengine_version(value: str) -> str:
    """Return one bounded canonical PEP 440 version string."""

    if not isinstance(value, str) or not value or value != value.strip():
        raise InvalidPolicyEngineVersionError(
            "policyengine_version must be a non-empty canonical version"
        )
    if len(value) > 128:
        raise InvalidPolicyEngineVersionError(
            "policyengine_version must be at most 128 characters"
        )
    try:
        parsed = Version(value)
    except InvalidVersion as error:
        raise InvalidPolicyEngineVersionError(
            "policyengine_version must be a canonical PEP 440 version"
        ) from error
    if str(parsed) != value or parsed == Version("0.0.0"):
        raise InvalidPolicyEngineVersionError(
            "policyengine_version must be a canonical non-placeholder version"
        )
    return value


class V2MetadataQueryService:
    """Assemble preview metadata using only an injected v2 read session."""

    def __init__(self, session: Session, *, running_policyengine_version: str):
        self._session = session
        self._running_policyengine_version = validate_policyengine_version(
            running_policyengine_version
        )

    def close(self) -> None:
        """Close the request-owned read session."""

        self._session.close()

    def get_metadata(
        self,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataResult:
        if country_id not in SUPPORTED_PREVIEW_COUNTRIES:
            raise UnsupportedPreviewCountryError(country_id)
        explicit_version = policyengine_version is not None
        selected_version = (
            validate_policyengine_version(policyengine_version)
            if explicit_version
            else self._running_policyengine_version
        )
        try:
            return self._read_metadata(
                country_id,
                selected_version,
                explicit_version=explicit_version,
            )
        except (
            MetadataCatalogUnavailableError,
            MetadataCatalogVersionNotFoundError,
        ):
            raise
        except SQLAlchemyError as error:
            raise MetadataCatalogUnavailableError(
                "the v2 metadata catalog cannot be queried"
            ) from error

    def _read_metadata(
        self,
        country_id: str,
        policyengine_version: str,
        *,
        explicit_version: bool,
    ) -> MetadataResult:
        model = self._session.exec(
            select(TaxBenefitModel).where(
                TaxBenefitModel.name == f"policyengine-{country_id}"
            )
        ).one_or_none()
        if model is None:
            if explicit_version:
                raise MetadataCatalogVersionNotFoundError(
                    f"PolicyEngine.py {policyengine_version} is not published "
                    f"for {country_id}"
                )
            raise MetadataCatalogUnavailableError(
                f"the {country_id} v2 metadata catalog is not initialized"
            )

        model_version = self._session.exec(
            select(TaxBenefitModelVersion).where(
                TaxBenefitModelVersion.model_id == model.id,
                TaxBenefitModelVersion.version == policyengine_version,
            )
        ).one_or_none()
        if model_version is None:
            if explicit_version:
                raise MetadataCatalogVersionNotFoundError(
                    f"PolicyEngine.py {policyengine_version} is not published "
                    f"for {country_id}"
                )
            raise MetadataCatalogUnavailableError(
                f"the running PolicyEngine.py {policyengine_version} catalog "
                f"is absent for {country_id}"
            )

        variables = self._session.exec(
            select(Variable)
            .where(Variable.tax_benefit_model_version_id == model_version.id)
            .order_by(Variable.name)
        ).all()
        nodes = self._session.exec(
            select(ParameterNode)
            .where(ParameterNode.tax_benefit_model_version_id == model_version.id)
            .order_by(ParameterNode.name)
        ).all()
        parameters = self._session.exec(
            select(Parameter)
            .where(Parameter.tax_benefit_model_version_id == model_version.id)
            .order_by(Parameter.name)
        ).all()
        parameter_values = self._session.exec(
            select(ParameterValue)
            .join(Parameter, Parameter.id == ParameterValue.parameter_id)
            .where(
                Parameter.tax_benefit_model_version_id == model_version.id,
                ParameterValue.policy_id.is_(None),
                ParameterValue.dynamic_id.is_(None),
            )
            .order_by(Parameter.name, ParameterValue.start_date)
        ).all()
        regions = self._session.exec(
            select(Region)
            .where(Region.tax_benefit_model_version_id == model_version.id)
            .order_by(Region.code)
        ).all()

        if not variables or not nodes or not parameters or not regions:
            raise MetadataCatalogUnavailableError(
                f"the {country_id} v2 metadata catalog is incomplete"
            )

        dataset_ids = {region.default_dataset_id for region in regions}
        datasets = self._session.exec(
            select(Dataset)
            .where(
                Dataset.id.in_(dataset_ids),
                Dataset.tax_benefit_model_version_id == model_version.id,
                Dataset.is_output_dataset.is_(False),
                Dataset.storage_path.is_(None),
            )
            .order_by(Dataset.name)
        ).all()
        if {dataset.id for dataset in datasets} != dataset_ids:
            raise MetadataCatalogUnavailableError(
                f"the {country_id} v2 region datasets are incomplete"
            )

        values_by_parameter = defaultdict(list)
        for value in parameter_values:
            values_by_parameter[value.parameter_id].append(
                MetadataParameterValue(
                    id=value.id,
                    value=value.value_json,
                    start_date=value.start_date,
                    end_date=value.end_date,
                )
            )

        national_region = next(
            (region for region in regions if region.code == country_id),
            None,
        )
        if national_region is None:
            raise MetadataCatalogUnavailableError(
                f"the {country_id} national v2 region is absent"
            )
        datasets_by_id = {dataset.id: dataset for dataset in datasets}
        national_dataset = datasets_by_id[national_region.default_dataset_id]
        time_periods = model_version.metadata_time_periods
        if (
            not isinstance(model_version.current_law_id, int)
            or not isinstance(time_periods, list)
            or not time_periods
            or any(not isinstance(year, int) for year in time_periods)
        ):
            raise MetadataCatalogUnavailableError(
                f"the {country_id} v2 model-version options are incomplete"
            )

        return MetadataResult(
            current_law_id=model_version.current_law_id,
            model=MetadataModel(
                id=model.id,
                name=model.name,
                description=model_version.description,
            ),
            model_version=MetadataModelVersion(
                id=model_version.id,
                model_id=model.id,
                version=model_version.version,
                description=model_version.description,
            ),
            variables=[
                MetadataVariable(
                    id=variable.id,
                    name=variable.name,
                    label=variable.label,
                    entity=variable.entity,
                    description=variable.description,
                    data_type=variable.data_type,
                    possible_values=variable.possible_values,
                    default_value=variable.default_value,
                    adds=variable.adds,
                    subtracts=variable.subtracts,
                )
                for variable in variables
            ],
            parameter_nodes=[
                MetadataParameterNode(
                    id=node.id,
                    name=node.name,
                    label=node.label,
                    description=node.description,
                )
                for node in nodes
            ],
            parameters=[
                MetadataParameter(
                    id=parameter.id,
                    name=parameter.name,
                    label=parameter.label,
                    description=parameter.description,
                    data_type=parameter.data_type,
                    unit=parameter.unit,
                    values=values_by_parameter[parameter.id],
                )
                for parameter in parameters
            ],
            datasets=[
                MetadataDataset(
                    id=dataset.id,
                    name=dataset.name,
                    description=dataset.description,
                    year=dataset.year,
                )
                for dataset in datasets
            ],
            regions=[
                MetadataRegion(
                    id=region.id,
                    code=region.code,
                    label=region.label,
                    region_type=region.region_type.value,
                    requires_filter=region.requires_filter,
                    filter_field=region.filter_field,
                    filter_value=region.filter_value,
                    filter_strategy=region.filter_strategy,
                    parent_code=region.parent_code,
                    state_code=region.state_code,
                    state_name=region.state_name,
                    default_dataset_id=region.default_dataset_id,
                )
                for region in regions
            ],
            economy_options=MetadataEconomyOptions(
                region=[
                    MetadataRegionOption(
                        name=region.code,
                        label=region.label,
                        type=region.region_type.value,
                    )
                    for region in regions
                ],
                time_period=[
                    MetadataTimePeriodOption(name=year, label=str(year))
                    for year in time_periods
                ],
                datasets=[
                    MetadataDatasetOption(
                        name=national_dataset.name,
                        label=national_dataset.description or national_dataset.name,
                    )
                ],
            ),
        )
