"""Versioned, framework-independent contracts for one v2 simulation."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from policyengine_api.query_parameters import CountryId

ContractText = Annotated[str, Field(min_length=1, max_length=255)]
ContractVersion = Literal[1]
Sha256Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
StorageUri = Annotated[
    str,
    Field(
        min_length=6,
        max_length=2048,
        pattern=r"^gs://[^/]+/.+$",
    ),
]
DatasetArtifactUri = Annotated[
    str,
    Field(
        min_length=6,
        max_length=2048,
        pattern=r"^(?:gs|hf)://[^/]+/.+$",
    ),
]


class StrictContractModel(BaseModel):
    """Reject undeclared fields and unstable non-finite values."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)


class SimulationRole(StrEnum):
    BASELINE = "baseline"
    REFORM = "reform"
    STANDALONE = "standalone"


class ArtifactMediaType(StrEnum):
    JSON = "application/json"
    PARQUET = "application/vnd.apache.parquet"


class DatasetArtifactMediaType(StrEnum):
    HDF5 = "application/x-hdf5"
    JSON = "application/json"
    PARQUET = "application/vnd.apache.parquet"


class DatasetProvenance(StrictContractModel):
    identity: ContractText
    uri: Annotated[str, Field(min_length=1, max_length=2048)]
    artifact_revision: ContractText
    data_package_name: ContractText
    data_package_version: ContractText


class BundleProvenance(StrictContractModel):
    policyengine_version: ContractText
    country_package_name: ContractText
    country_package_version: ContractText
    dataset: DatasetProvenance
    bundle_manifest_sha256: Sha256Digest


class ArtifactReference(StrictContractModel):
    uri: StorageUri
    media_type: ArtifactMediaType
    content_sha256: Sha256Digest
    size_bytes: Annotated[int, Field(ge=0)]


class DatasetArtifactReference(StrictContractModel):
    uri: DatasetArtifactUri
    media_type: DatasetArtifactMediaType
    content_sha256: Sha256Digest
    size_bytes: Annotated[int, Field(ge=0)] | None = None


class DatasetPopulationInput(StrictContractModel):
    kind: Literal["dataset"] = "dataset"
    artifact: DatasetArtifactReference


class HouseholdPopulationInput(StrictContractModel):
    kind: Literal["household"] = "household"
    document: dict[str, JsonValue]


PopulationInput = Annotated[
    DatasetPopulationInput | HouseholdPopulationInput,
    Field(discriminator="kind"),
]


class GeographySelection(StrictContractModel):
    country: CountryId
    region: ContractText
    filter_field: ContractText | None = None
    filter_value: ContractText | None = None
    filter_strategy: ContractText | None = None

    @model_validator(mode="after")
    def require_complete_filter(self) -> GeographySelection:
        if (self.filter_field is None) != (self.filter_value is None):
            raise ValueError("filter_field and filter_value must be supplied together")
        if self.filter_strategy is not None and self.filter_field is None:
            raise ValueError("filter_strategy requires filter_field and filter_value")
        return self


class RequestedSimulationOutput(StrictContractModel):
    schema_version: ContractVersion = 1
    variables: Annotated[tuple[ContractText, ...], Field(min_length=1)]

    @field_validator("variables")
    @classmethod
    def require_unique_variables(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("requested variables must be unique")
        return value


class SimulationExecutionInput(StrictContractModel):
    contract_version: ContractVersion = 1
    evaluation_id: UUID
    simulation_execution_id: UUID
    role: SimulationRole
    policy: dict[str, JsonValue]
    population: PopulationInput
    year: Annotated[int, Field(ge=1900, le=2200)]
    geography: GeographySelection
    options: dict[str, JsonValue] = Field(default_factory=dict)
    requested_output: RequestedSimulationOutput
    bundle: BundleProvenance


class RowIdentity(StrictContractModel):
    schema_version: ContractVersion = 1
    identifier_columns: Annotated[tuple[ContractText, ...], Field(min_length=1)]
    row_count: Annotated[int, Field(ge=0)]
    identity_sha256: Sha256Digest

    @field_validator("identifier_columns")
    @classmethod
    def require_unique_columns(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("row identifier columns must be unique")
        return value


class SimulationArtifactDescriptor(StrictContractModel):
    contract_version: ContractVersion = 1
    evaluation_id: UUID
    simulation_execution_id: UUID
    role: SimulationRole
    artifact: ArtifactReference
    output_schema_version: ContractVersion = 1
    row_identity: RowIdentity
    bundle: BundleProvenance
    calculation_provenance: dict[str, JsonValue] | None = None
