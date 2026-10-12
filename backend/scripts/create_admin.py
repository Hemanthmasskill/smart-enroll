import argparse
import getpass
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add backend directory to sys.path so app modules can be imported
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.core.security import get_password_hash


def create_admin(email: str, full_name: str, password: str) -> bool:
    """
    Controlled administrative utility to create an admin account directly.
    Normalizes email, hashes password with Argon2id, and stores the user
    with role='admin' and applicant_id=None.
    """
    normalized_email = email.strip().lower()
    if not normalized_email:
        print("Error: Email cannot be empty.", file=sys.stderr)
        return False
    if not full_name.strip():
        print("Error: Full name cannot be empty.", file=sys.stderr)
        return False
    if not password:
        print("Error: Password cannot be empty.", file=sys.stderr)
        return False

    client = MongoClient(settings.MONGODB_URI)
    db = client[settings.DATABASE_NAME]

    # Ensure unique index exists on email
    db["users"].create_index("email", unique=True)

    # Check for existing email
    existing_user = db["users"].find_one({"email": normalized_email})
    if existing_user:
        print(f"Error: User with email '{normalized_email}' already exists.", file=sys.stderr)
        client.close()
        return False

    hashed_password = get_password_hash(password)
    admin_doc = {
        "email": normalized_email,
        "hashed_password": hashed_password,
        "full_name": full_name.strip(),
        "role": "admin",
        "applicant_id": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        db["users"].insert_one(admin_doc)
        print(f"Successfully created admin user: {normalized_email} ({full_name.strip()})")
        client.close()
        return True
    except DuplicateKeyError:
        print(f"Error: User with email '{normalized_email}' already exists.", file=sys.stderr)
        client.close()
        return False
    except Exception as e:
        print(f"Error creating admin: {e}", file=sys.stderr)
        client.close()
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Controlled Admin Creation Utility for Smart Enroll."
    )
    parser.add_argument(
        "--email",
        type=str,
        help="Admin email address",
        default=None,
    )
    parser.add_argument(
        "--name",
        type=str,
        help="Admin full name",
        default=None,
    )

    args = parser.parse_args()

    email = args.email
    if not email:
        try:
            email = input("Enter admin email: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            sys.exit(1)

    name = args.name
    if not name:
        try:
            name = input("Enter admin full name: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            sys.exit(1)

    try:
        password = getpass.getpass("Enter admin password: ")
        confirm_password = getpass.getpass("Confirm admin password: ")
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        sys.exit(1)

    if password != confirm_password:
        print("Error: Passwords do not match.", file=sys.stderr)
        sys.exit(1)

    success = create_admin(email=email, full_name=name, password=password)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
