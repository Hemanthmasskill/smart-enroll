from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class RuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ruleId: str
    name: str
    description: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class ProgrammeRulesResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    programmeId: str
    version: str
    effectiveFrom: str
    name: str
    shortName: str
    degreeLevel: str
    allowedDegreeFamilies: list[str]
    minPercentage: float
    cgpaToPercentageFactor: float = 9.5
    mathematicsRequirement: str
    requiredDocumentTypes: list[str]
    entranceRequired: bool = False
    rules: list[dict[str, Any]] = Field(default_factory=list)
