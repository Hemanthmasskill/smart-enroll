import logging
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from app.core.config import settings

logger = logging.getLogger(__name__)


class DatabaseInitializationError(RuntimeError):
    """Raised when critical database constraints or indexes cannot be initialized."""

    pass

client: MongoClient | None = None


def connect_to_mongo():
    global client
    client = MongoClient(settings.MONGODB_URI)
    db = client[settings.DATABASE_NAME]

    def _create_unique_index(collection_name: str, keys, **kwargs):
        coll = db[collection_name]
        try:
            coll.create_index(keys, unique=True, **kwargs)
        except DuplicateKeyError as e:
            logger.critical(
                "Database initialization failed: cannot create unique index on collection '%s' with keys %s "
                "because duplicate records exist in the database (%s). Database startup halted non-destructively. "
                "Run 'python backend/scripts/dedupe_applications.py' to inspect and resolve conflicting records.",
                collection_name,
                keys,
                e,
            )
            raise DatabaseInitializationError(
                f"Cannot create unique index on collection '{collection_name}' with keys {keys} due to duplicate records: {e}. "
                f"Startup halted without deleting data. Resolve duplicates using 'python backend/scripts/dedupe_applications.py'."
            ) from e
        except Exception as e:
            logger.critical(
                "Unexpected error creating index on '%s' with keys %s: %s",
                collection_name,
                keys,
                e,
                exc_info=True,
            )
            raise DatabaseInitializationError(f"Failed to create index on '{collection_name}': {e}") from e

    # 1. users unique indexes
    _create_unique_index("users", "email")
    _create_unique_index("users", "applicant_id", sparse=True)

    # 2. applications unique indexes (strictly non-destructive: fails startup if duplicates exist)
    _create_unique_index("applications", "applicationId", sparse=True)
    _create_unique_index("applications", "userId", sparse=True)

    # 3. documents unique indexes (no swallowing of DuplicateKeyError)
    _create_unique_index("documents", [("applicationId", 1), ("documentType", 1)])
    _create_unique_index("documents", "documentId", sparse=True)

    # Ensure indexes on orchestration_runs
    try:
        db["orchestration_runs"].create_index("runId", unique=True, sparse=True)
        db["orchestration_runs"].create_index([("applicationId", 1), ("startedAt", -1)])
    except Exception as e:
        logger.error("Failed to initialize standard orchestration_runs indexes: %s", e, exc_info=True)
        raise DatabaseInitializationError(f"Failed to create standard orchestration_runs indexes: {e}") from e

    # Atomic concurrency safeguard: at most one RUNNING or RECOVERING orchestration per application
    # 1. Clean up obsolete partial index definitions (e.g., RUNNING-only legacy index from earlier increments)
    try:
        existing_indexes = db["orchestration_runs"].index_information()
        for idx_name, idx_info in existing_indexes.items():
            if idx_info.get("key") == [("applicationId", 1)] and "partialFilterExpression" in idx_info:
                pfe = idx_info.get("partialFilterExpression", {})
                if pfe.get("status") != {"$in": ["RUNNING", "RECOVERING"]}:
                    logger.info("Migrating orchestration index: dropping legacy index '%s' with filter %s", idx_name, pfe)
                    db["orchestration_runs"].drop_index(idx_name)
    except Exception as e:
        logger.error("Failed to inspect or drop legacy orchestration indexes: %s", e, exc_info=True)
        raise DatabaseInitializationError(f"Failed to inspect or drop legacy orchestration indexes: {e}") from e

    # 2. Create the unique partial index covering both RUNNING and RECOVERING executions
    try:
        db["orchestration_runs"].create_index(
            [("applicationId", 1)],
            unique=True,
            partialFilterExpression={"status": {"$in": ["RUNNING", "RECOVERING"]}},
        )
    except DuplicateKeyError as e:
        conflicts = list(
            db["orchestration_runs"].aggregate([
                {"$match": {"status": {"$in": ["RUNNING", "RECOVERING"]}}},
                {"$group": {"_id": "$applicationId", "count": {"$sum": 1}, "runIds": {"$push": "$runId"}}},
                {"$match": {"count": {"$gt": 1}}},
            ])
        )
        logger.critical(
            "Database initialization failed: Cannot create unique partial index on orchestration_runs because duplicate active/recovering runs exist. Conflicting applications: %s. Detail: %s",
            conflicts,
            e,
        )
        raise DatabaseInitializationError(
            f"Cannot create unique partial index on orchestration_runs due to duplicate active/recovering runs: {conflicts}"
        ) from e
    except Exception as e:
        logger.critical(
            "Database initialization failed: Unexpected error while creating unique partial index on orchestration_runs: %s",
            e,
            exc_info=True,
        )
        raise DatabaseInitializationError(
            f"Failed to create unique partial index on orchestration_runs: {e}"
        ) from e

    # Ensure storage directory exists
    try:
        settings.storage_path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.warning("Could not create storage directory %s: %s", settings.storage_path, e)


def close_mongo_connection():
    global client
    if client is not None:
        client.close()
        client = None


def get_db():
    global client
    if client is None:
        connect_to_mongo()
    return client[settings.DATABASE_NAME]
