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
    db["users"].create_index("email", unique=True)
    db["users"].create_index("applicant_id", unique=True, sparse=True)

    # Ensure unique index on applicationId, resolving any legacy duplicate seed records if present
    try:
        db["applications"].create_index("applicationId", unique=True, sparse=True)
    except DuplicateKeyError:
        seen = set()
        for doc in db["applications"].find({}, sort=[("_id", -1)]):
            app_id = doc.get("applicationId")
            if app_id:
                if app_id in seen:
                    db["applications"].delete_one({"_id": doc["_id"]})
                else:
                    seen.add(app_id)
        db["applications"].create_index("applicationId", unique=True, sparse=True)

    # Ensure unique index on userId (one application per applicant)
    try:
        db["applications"].create_index("userId", unique=True, sparse=True)
    except DuplicateKeyError:
        seen = set()
        for doc in db["applications"].find({"userId": {"$exists": True, "$ne": None}}, sort=[("_id", -1)]):
            uid = doc.get("userId")
            if uid:
                if uid in seen:
                    db["applications"].delete_one({"_id": doc["_id"]})
                else:
                    seen.add(uid)
        db["applications"].create_index("userId", unique=True, sparse=True)

    # Ensure unique compound index on (applicationId, documentType) for documents
    try:
        db["documents"].create_index([("applicationId", 1), ("documentType", 1)], unique=True)
    except DuplicateKeyError:
        pass

    try:
        db["documents"].create_index("documentId", unique=True, sparse=True)
    except DuplicateKeyError:
        pass

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
