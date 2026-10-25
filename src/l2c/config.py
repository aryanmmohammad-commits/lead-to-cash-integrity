"""Validated configuration; business values and source names stay in YAML."""

import codecs
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal, TypeVar

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StringConstraints,
    ValidationError,
    ValidationInfo,
    field_validator,
)

from l2c.paths import DEFAULT_RULES_PATH, get_mapping_path, resolve_repo_path

Text = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
TextList = Annotated[list[Text], Field(min_length=1)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
NonNegativeFloat = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]


class ConfigError(ValueError):
    """A missing, malformed or invalid configuration file."""


class _ConfigLoader(yaml.SafeLoader):
    """Let Pydantic validate dates so invalid unquoted dates name their key."""

    yaml_implicit_resolvers = {
        initial: [
            (tag, pattern) for tag, pattern in resolvers if tag != "tag:yaml.org,2002:timestamp"
        ]
        for initial, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RulesConfig(ConfigModel):
    as_of_date: date
    base_currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
    lifecycle_order: TextList
    lead_status_allowed: TextList
    customer_lead_status: Text | None
    original_source_allowed: TextList
    open_deal_stages: TextList
    closed_won_stage: Text
    closed_lost_stage: Text
    stale_open_deal_days: NonNegativeInt
    territory_by_country: Annotated[dict[Text, TextList], Field(min_length=1)]
    default_territory: Text
    won_not_billed_days: NonNegativeInt
    amount_tolerance_pct: NonNegativeFloat
    start_date_tolerance_days: NonNegativeInt
    renewal_window_days: NonNegativeInt
    push_line_item_tolerance_pct: NonNegativeFloat
    stale_exception_days: NonNegativeInt
    sanity_max_drop_pct: Annotated[float, Field(strict=True, ge=0, le=100, allow_inf_nan=False)]
    arr_months: Annotated[int, Field(strict=True, gt=0)]
    term_tolerance_months: NonNegativeInt
    generic_email_domains: TextList
    draft_order_status: Text
    initial_order_version: Annotated[int, Field(strict=True, gt=0)]
    new_deal_motion: Text
    change_deal_motions: TextList
    quarantine_reasons: TextList

    @field_validator("as_of_date", mode="before")
    @classmethod
    def validate_as_of_date(cls, value: object) -> date:
        if type(value) is date:
            return value
        if isinstance(value, str):
            try:
                parsed = date.fromisoformat(value)
                if parsed.isoformat() == value:
                    return parsed
            except ValueError:
                pass
        raise ValueError("must be a valid date in YYYY-MM-DD format")

    @field_validator(
        "lifecycle_order",
        "lead_status_allowed",
        "original_source_allowed",
        "open_deal_stages",
        "generic_email_domains",
        "change_deal_motions",
        "quarantine_reasons",
    )
    @classmethod
    def validate_unique_values(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("must not contain duplicate values")
        return values

    @field_validator("customer_lead_status")
    @classmethod
    def validate_customer_status(cls, value: str | None, info: ValidationInfo) -> str | None:
        allowed = info.data.get("lead_status_allowed")
        if value is not None and allowed is not None and value not in allowed:
            raise ValueError("must be null or a member of lead_status_allowed")
        return value

    @field_validator("change_deal_motions")
    @classmethod
    def validate_change_motions(cls, values: list[str], info: ValidationInfo) -> list[str]:
        if info.data.get("new_deal_motion") in values:
            raise ValueError("must not contain new_deal_motion")
        return values

    @field_validator("closed_won_stage", "closed_lost_stage")
    @classmethod
    def validate_closed_stage(cls, value: str, info: ValidationInfo) -> str:
        if value in info.data.get("open_deal_stages", []):
            raise ValueError("must not also appear in open_deal_stages")
        if info.field_name == "closed_lost_stage" and value == info.data.get("closed_won_stage"):
            raise ValueError("must differ from closed_won_stage")
        return value

    @field_validator("territory_by_country")
    @classmethod
    def validate_country_assignment(cls, territories: dict[str, list[str]]) -> dict[str, list[str]]:
        seen: set[str] = set()
        for countries in territories.values():
            for country in countries:
                if country in seen:
                    raise ValueError(f"country {country!r} must appear only once")
                seen.add(country)
        return territories


class FileFormat(ConfigModel):
    delimiter: Literal[",", ";"]
    encoding: Text
    date_format: Text
    decimal: Literal[".", ","]
    thousands: Literal["", "'", "."]

    @field_validator("encoding")
    @classmethod
    def validate_encoding(cls, value: str) -> str:
        try:
            codecs.lookup(value)
        except LookupError as exc:
            raise ValueError(f"unknown encoding {value!r}") from exc
        return value

    @field_validator("date_format")
    @classmethod
    def validate_date_format(cls, value: str) -> str:
        sample = date(2004, 11, 23)
        try:
            if datetime.strptime(sample.strftime(value), value).date() == sample:
                return value
        except (ValueError, OverflowError):
            pass
        raise ValueError("must be a strptime format containing a year, month and day")

    @field_validator("thousands")
    @classmethod
    def validate_number_separators(cls, value: str, info: ValidationInfo) -> str:
        if value and value == info.data.get("decimal"):
            raise ValueError("must differ from decimal")
        return value


class TableMapping(ConfigModel):
    file: Text
    format: FileFormat
    columns: Annotated[dict[Identifier, Text], Field(min_length=1)]
    values: dict[Identifier, dict[str, str]] = Field(default_factory=dict)

    @field_validator("values")
    @classmethod
    def validate_value_columns(
        cls, value: dict[str, dict[str, str]], info: ValidationInfo
    ) -> dict[str, dict[str, str]]:
        columns = info.data.get("columns")
        if columns is not None:
            unknown = value.keys() - columns.keys()
            if unknown:
                raise ValueError(
                    f"columns not present in columns map: {', '.join(sorted(unknown))}"
                )
        return value


class MappingConfig(RootModel[Annotated[dict[Identifier, TableMapping], Field(min_length=1)]]):
    """Table names are the top-level YAML keys, as used by dbt's mapping var."""

    @property
    def tables(self) -> dict[str, TableMapping]:
        return self.root


ModelT = TypeVar("ModelT", bound=BaseModel)


def _load_config(path: Path, model: type[ModelT]) -> ModelT:
    try:
        contents = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise ConfigError(f"Cannot read configuration {path}: {exc}") from exc
    try:
        data = yaml.load(contents, Loader=_ConfigLoader)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        errors = []
        for error in exc.errors(include_url=False):
            key = ".".join(str(part) for part in error["loc"]) or "<root>"
            errors.append(f"  {key}: {error['msg']}")
        raise ConfigError(f"Invalid configuration in {path}:\n" + "\n".join(errors)) from exc


def load_rules(path: str | Path | None = None) -> RulesConfig:
    return _load_config(resolve_repo_path(path or DEFAULT_RULES_PATH), RulesConfig)


def load_mapping(path: str | Path | None = None) -> MappingConfig:
    return _load_config(get_mapping_path(path), MappingConfig)
