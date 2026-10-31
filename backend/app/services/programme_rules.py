import logging
from typing import Any
from pymongo.database import Database

logger = logging.getLogger(__name__)

CANONICAL_PROGRAMME_RULES_V1: list[dict[str, Any]] = [
    {
        "programmeId": "mca",
        "version": "1.0.0",
        "effectiveFrom": "2026-01-01T00:00:00Z",
        "name": "Master of Computer Applications",
        "shortName": "MCA",
        "degreeLevel": "BACHELORS",
        "allowedDegreeFamilies": ["ANY"],
        "minPercentage": 50.0,
        "cgpaToPercentageFactor": 9.5,
        "mathematicsRequirement": "10+2_OR_GRADUATION",
        "requiredDocumentTypes": [
            "10TH_MARKSHEET",
            "12TH_MARKSHEET",
            "UG_MARKSHEET",
            "DEGREE_CERTIFICATE",
            "TRANSFER_CERTIFICATE",
            "GOVERNMENT_ID",
        ],
        "entranceRequired": False,
        "rules": [
            {
                "ruleId": "MIN_QUALIFICATION",
                "name": "Bachelor's Degree Qualification",
                "requiredDegreeLevel": "BACHELORS",
                "allowedDegreeFamilies": ["ANY"],
            },
            {
                "ruleId": "MIN_PERCENTAGE",
                "name": "Minimum 50% Aggregate",
                "minPercentage": 50.0,
                "cgpaToPercentageFactor": 9.5,
            },
            {
                "ruleId": "MATHEMATICS_REQUIREMENT",
                "name": "Mathematics at 10+2 or Graduation Level",
                "requirementLevel": "10+2_OR_GRADUATION",
            },
            {
                "ruleId": "DOCUMENT_COMPLETENESS",
                "name": "All 6 Required Documents Validated",
                "requiredDocumentTypes": [
                    "10TH_MARKSHEET",
                    "12TH_MARKSHEET",
                    "UG_MARKSHEET",
                    "DEGREE_CERTIFICATE",
                    "TRANSFER_CERTIFICATE",
                    "GOVERNMENT_ID",
                ],
            },
            {
                "ruleId": "ENTRANCE_EXAM",
                "name": "Entrance Exam Requirement",
                "required": False,
            },
        ],
    },
    {
        "programmeId": "mba",
        "version": "1.0.0",
        "effectiveFrom": "2026-01-01T00:00:00Z",
        "name": "Master of Business Administration",
        "shortName": "MBA",
        "degreeLevel": "BACHELORS",
        "allowedDegreeFamilies": ["ANY"],
        "minPercentage": 50.0,
        "cgpaToPercentageFactor": 9.5,
        "mathematicsRequirement": "NONE",
        "requiredDocumentTypes": [
            "10TH_MARKSHEET",
            "12TH_MARKSHEET",
            "UG_MARKSHEET",
            "DEGREE_CERTIFICATE",
            "TRANSFER_CERTIFICATE",
            "GOVERNMENT_ID",
        ],
        "entranceRequired": False,
        "rules": [
            {
                "ruleId": "MIN_QUALIFICATION",
                "name": "Bachelor's Degree (Any Discipline)",
                "requiredDegreeLevel": "BACHELORS",
                "allowedDegreeFamilies": ["ANY"],
            },
            {
                "ruleId": "MIN_PERCENTAGE",
                "name": "Minimum 50% Aggregate",
                "minPercentage": 50.0,
                "cgpaToPercentageFactor": 9.5,
            },
            {
                "ruleId": "MATHEMATICS_REQUIREMENT",
                "name": "Mathematics Prerequisite",
                "requirementLevel": "NONE",
            },
            {
                "ruleId": "DOCUMENT_COMPLETENESS",
                "name": "All 6 Required Documents Validated",
                "requiredDocumentTypes": [
                    "10TH_MARKSHEET",
                    "12TH_MARKSHEET",
                    "UG_MARKSHEET",
                    "DEGREE_CERTIFICATE",
                    "TRANSFER_CERTIFICATE",
                    "GOVERNMENT_ID",
                ],
            },
            {
                "ruleId": "ENTRANCE_EXAM",
                "name": "Entrance Exam Requirement",
                "required": False,
            },
        ],
    },
    {
        "programmeId": "msc-cs",
        "version": "1.0.0",
        "effectiveFrom": "2026-01-01T00:00:00Z",
        "name": "Master of Science in Computer Science",
        "shortName": "M.Sc Computer Science",
        "degreeLevel": "BACHELORS",
        "allowedDegreeFamilies": ["ANY"],
        "minPercentage": 55.0,
        "cgpaToPercentageFactor": 9.5,
        "mathematicsRequirement": "GRADUATION",
        "requiredDocumentTypes": [
            "10TH_MARKSHEET",
            "12TH_MARKSHEET",
            "UG_MARKSHEET",
            "DEGREE_CERTIFICATE",
            "TRANSFER_CERTIFICATE",
            "GOVERNMENT_ID",
        ],
        "entranceRequired": False,
        "rules": [
            {
                "ruleId": "MIN_QUALIFICATION",
                "name": "Bachelor's Degree Qualification",
                "requiredDegreeLevel": "BACHELORS",
                "allowedDegreeFamilies": ["ANY"],
            },
            {
                "ruleId": "MIN_PERCENTAGE",
                "name": "Minimum 55% Aggregate",
                "minPercentage": 55.0,
                "cgpaToPercentageFactor": 9.5,
            },
            {
                "ruleId": "MATHEMATICS_REQUIREMENT",
                "name": "Mathematics at Graduation Level",
                "requirementLevel": "GRADUATION",
            },
            {
                "ruleId": "DOCUMENT_COMPLETENESS",
                "name": "All 6 Required Documents Validated",
                "requiredDocumentTypes": [
                    "10TH_MARKSHEET",
                    "12TH_MARKSHEET",
                    "UG_MARKSHEET",
                    "DEGREE_CERTIFICATE",
                    "TRANSFER_CERTIFICATE",
                    "GOVERNMENT_ID",
                ],
            },
            {
                "ruleId": "ENTRANCE_EXAM",
                "name": "Entrance Exam Requirement",
                "required": False,
            },
        ],
    },
    {
        "programmeId": "mtech-cs",
        "version": "1.0.0",
        "effectiveFrom": "2026-01-01T00:00:00Z",
        "name": "Master of Technology in Computer Science",
        "shortName": "M.Tech Computer Science",
        "degreeLevel": "BACHELORS",
        "allowedDegreeFamilies": ["ENGINEERING_TECHNOLOGY"],
        "minPercentage": 60.0,
        "cgpaToPercentageFactor": 9.5,
        "mathematicsRequirement": "GRADUATION",
        "requiredDocumentTypes": [
            "10TH_MARKSHEET",
            "12TH_MARKSHEET",
            "UG_MARKSHEET",
            "DEGREE_CERTIFICATE",
            "TRANSFER_CERTIFICATE",
            "GOVERNMENT_ID",
        ],
        "entranceRequired": False,
        "rules": [
            {
                "ruleId": "MIN_QUALIFICATION",
                "name": "Bachelor's Degree in Engineering or Technology",
                "requiredDegreeLevel": "BACHELORS",
                "allowedDegreeFamilies": ["ENGINEERING_TECHNOLOGY"],
            },
            {
                "ruleId": "MIN_PERCENTAGE",
                "name": "Minimum 60% Aggregate",
                "minPercentage": 60.0,
                "cgpaToPercentageFactor": 9.5,
            },
            {
                "ruleId": "MATHEMATICS_REQUIREMENT",
                "name": "Mathematics at Graduation Level",
                "requirementLevel": "GRADUATION",
            },
            {
                "ruleId": "DOCUMENT_COMPLETENESS",
                "name": "All 6 Required Documents Validated",
                "requiredDocumentTypes": [
                    "10TH_MARKSHEET",
                    "12TH_MARKSHEET",
                    "UG_MARKSHEET",
                    "DEGREE_CERTIFICATE",
                    "TRANSFER_CERTIFICATE",
                    "GOVERNMENT_ID",
                ],
            },
            {
                "ruleId": "ENTRANCE_EXAM",
                "name": "Entrance Exam Requirement",
                "required": False,
            },
        ],
    },
]


def seed_programme_rules(db: Database) -> int:
    """
    Idempotently seeds the four canonical programme rules into the programme_rules collection.
    Uses update_one with upsert=True based on (programmeId, version).
    Returns count of rules seeded.
    """
    collection = db["programme_rules"]
    count = 0
    for rule in CANONICAL_PROGRAMME_RULES_V1:
        clean_rule = dict(rule)
        filter_doc = {
            "programmeId": clean_rule["programmeId"],
            "version": clean_rule["version"],
        }
        collection.update_one(filter_doc, {"$set": clean_rule}, upsert=True)
        count += 1
    logger.info("Idempotently seeded %d programme rules into programme_rules collection.", count)
    return count


def get_programme_rules(db: Database, programme_id: str, version: str | None = None) -> dict[str, Any] | None:
    """
    Retrieve programme rules by programmeId (case-insensitive).
    If version is provided, returns that specific version; otherwise returns the latest effective version.
    """
    pid = programme_id.strip().lower()
    query: dict[str, Any] = {"programmeId": pid}
    if version:
        query["version"] = version.strip()

    # Sort by version descending if no specific version requested
    rule = db["programme_rules"].find_one(query, {"_id": 0}, sort=[("version", -1)])
    return rule
