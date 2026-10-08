# Name: Brian Taylor
# Date: October 7, 2026
# Course: SDC435L
# Project: GitHub Activity Explorer
# Purpose: Import GitHub Archive records into Redis for CRUD and analysis.

import io
import json
import zipfile
from datetime import datetime
from pathlib import Path

import redis


PROJECT_FOLDER = Path(__file__).resolve().parent
DATASET_PATH = PROJECT_FOLDER / "data" / "GitHubArchive-Dataset.zip"

# Use database 5 and a project prefix to separate these records.
DATABASE_NUMBER = 5
PREFIX = "sdc435l:"

# Import a manageable starting sample from each file.
# These samples are not representative of all GitHub activity.
IMPORT_LIMIT = 5000


def read_records(archive, filename):
    """Read newline-delimited JSON without extracting the ZIP."""
    archive_path = "GitHubArchive-Dataset/" + filename

    with archive.open(archive_path) as binary_file:
        with io.TextIOWrapper(binary_file, encoding="utf-8") as text_file:
            count = 0
            for line_number, line in enumerate(text_file, start=1):
                if not line.strip():
                    continue

                try:
                    record = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        f"{filename}, line {line_number}: {error}"
                    ) from error

                yield record
                count += 1

                if count >= IMPORT_LIMIT:
                    break


def import_dataset(database):
    """Store each record as a JSON string under a unique Redis key."""
    if not DATASET_PATH.is_file():
        raise FileNotFoundError(f"Dataset not found: {DATASET_PATH}")

    sources = [
        ("Sample_Repos.json", "repo", "repo_name"),
        ("Commits.json", "commit", "commit"),
        ("Languages.json", "language", "repo_name"),
    ]

    with zipfile.ZipFile(DATASET_PATH) as archive:
        for filename, category, identifier_field in sources:
            count = 0

            # Batch writes to reduce individual network round trips.
            pipeline = database.pipeline(transaction=False)

            for record in read_records(archive, filename):
                identifier = record.get(identifier_field)

                if not isinstance(identifier, str) or not identifier:
                    raise ValueError(
                        f"{filename}: missing or invalid {identifier_field}"
                    )

                key = f"{PREFIX}{category}:{identifier}"
                pipeline.set(key, json.dumps(record))
                count += 1

                if count % 500 == 0:
                    pipeline.execute()

            pipeline.execute()
            print(f"{filename}: processed {count} records.")

    print("Import complete. Existing matching keys were replaced.")
    print("Results describe only the imported sample.")


def choose_record_key():
    """Build a Redis key from the record category and identifier."""
    category = input(
        "Record category (repo, commit, language): "
    ).strip().lower()

    if category not in ("repo", "commit", "language"):
        raise ValueError("Choose repo, commit, or language.")

    identifier = input(
        "Repository name or full commit hash: "
    ).strip()

    if not identifier:
        raise ValueError("The identifier cannot be blank.")

    return category, identifier, f"{PREFIX}{category}:{identifier}"


def get_record_input(category, identifier):
    """Accept a JSON object and validate its identifying field."""
    print('Enter a JSON object, such as:')
    print('{"repo_name": "britay2664/demo", "watch_count": "10"}')

    record = json.loads(input("JSON record: "))

    if not isinstance(record, dict):
        raise ValueError("The record must be a JSON object.")

    field = "commit" if category == "commit" else "repo_name"

    if record.get(field) != identifier:
        raise ValueError(f"'{field}' must match '{identifier}'.")

    # Validate fields used by the repository ranking feature.
    if category == "repo":
        count = record.get("watch_count")
        if isinstance(count, bool) or not isinstance(count, (str, int)):
            raise ValueError("watch_count must be a nonnegative integer.")
        if int(count) < 0:
            raise ValueError("watch_count cannot be negative.")

    return record

def stored_records(database, category):
    """Read current project records so analysis reflects CRUD changes."""
    pattern = f"{PREFIX}{category}:*"

    # SCAN can return a key more than once; count each key once.
    seen = set()
    for key in database.scan_iter(match=pattern):
        if key in seen:
            continue
        seen.add(key)

        value = database.get(key)
        if value is not None:
            record = json.loads(value)
            if isinstance(record, dict):
                yield record


def repository_ranking(database):
    """Rank imported repositories by their recorded watch counts."""
    rankings = []
    skipped = 0

    for record in stored_records(database, "repo"):
        try:
            name = record["repo_name"]
            count = int(record["watch_count"])
            if not isinstance(name, str) or count < 0:
                raise ValueError
            rankings.append((name, count))
        except (KeyError, TypeError, ValueError):
            skipped += 1

    rankings.sort(key=lambda item: (-item[1], item[0]))

    print("\nTop 10 repositories by recorded watch count")
    print("These are historical dataset values, not live GitHub counts.")

    if not rankings:
        print("No valid repository records found.")

    for position, (name, count) in enumerate(rankings[:10], start=1):
        print(f"{position}. {name}: {count:,}")

    if skipped:
        print(f"Skipped {skipped} invalid repository records.")


def contributor_lookup(database):
    """Find stored commits by an exact author name."""
    name = input("Enter the author's full name: ").strip()
    if not name:
        print("Enter a name.")
        return

    matches = 0
    print(f"\nStored commits by {name}")

    for record in stored_records(database, "commit"):
        author = record.get("author")
        if not isinstance(author, dict):
            continue

        author_name = author.get("name")
        if not isinstance(author_name, str):
            continue

        if author_name.casefold() != name.casefold():
            continue

        matches += 1

        # Limit displayed results while counting all matching records.
        if matches <= 20:
            repositories = record.get("repo_name", [])
            if isinstance(repositories, str):
                repositories = [repositories]

            subject = " ".join(
                str(record.get("subject", "")).split()
            )
            print(f"\nCommit: {record.get('commit', 'Unknown')}")
            print("Repositories:", ", ".join(
                str(repo) for repo in repositories
            ))
            print("Subject:", subject[:150])

    print(f"\nTotal matching commits: {matches}")
    if matches > 20:
        print("Only the first 20 matches are displayed.")
    print("Author names may be shared by different people.")
    print("Results cover only stored commits and are not chronological.")


def language_breakdown(database):
    """Display a repository's recorded languages and byte counts."""
    name = input("Enter the repository name: ").strip()
    value = database.get(f"{PREFIX}language:{name}")

    if value is None:
        print("No language record found in the imported sample.")
        return

    record = json.loads(value)
    languages = record.get("language")

    if not isinstance(languages, list):
        print("This record has an invalid language list.")
        return

    totals = {}
    for item in languages:
        try:
            language = item["name"]
            size = int(item["bytes"])
            if not isinstance(language, str) or size < 0:
                raise ValueError
            totals[language] = totals.get(language, 0) + size
        except (KeyError, TypeError, ValueError):
            print("Skipped an invalid language entry.")

    total_bytes = sum(totals.values())
    print(f"\nLanguage breakdown for {name}")

    if not totals:
        print("No valid language entries found.")
        return

    for language, size in sorted(
        totals.items(), key=lambda item: (-item[1], item[0])
    ):
        percentage = size / total_bytes * 100 if total_bytes else 0
        print(f"{language}: {size:,} bytes ({percentage:.1f}%)")

    print(f"Total recorded bytes: {total_bytes:,}")

def crud_menu(database):
    """Let the user import, create, read, update, and delete records."""
    while True:
        print("\nGitHub Activity Explorer")
        print("System date and time:",
              datetime.now().astimezone().isoformat(
                  sep=" ", timespec="seconds"
              ))
        print("1. Import dataset")
        print("2. Create a record")
        print("3. Read a record")
        print("4. Update a record")
        print("5. Delete a record")
        print("6. Repository watch count ranking")
        print("7. Contributor commit lookup")
        print("8. Repository language breakdown")
        print("0. Exit")

        choice = input("Select an option: ").strip()

        try:
            if choice == "1":
                import_dataset(database)

            elif choice in ("2", "3", "4", "5"):
                category, identifier, key = choose_record_key()

                # CREATE: Add a record without replacing an existing key.
                if choice == "2":
                    record = get_record_input(category, identifier)
                    created = database.set(
                        key, json.dumps(record), nx=True
                    )
                    print("Record created." if created else
                          "Record already exists. Use Update.")

                # READ: Retrieve and display a stored JSON record.
                elif choice == "3":
                    value = database.get(key)
                    if value is None:
                        print("Record not found.")
                    else:
                        print(json.dumps(json.loads(value), indent=2))

                # UPDATE: Replace an existing record with supplied JSON.
                elif choice == "4":
                    if not database.exists(key):
                        print("Record not found.")
                        continue

                    print("Current record:")
                    print(json.dumps(
                        json.loads(database.get(key)), indent=2
                    ))
                    print("Enter the complete replacement record.")
                    record = get_record_input(category, identifier)
                    updated = database.set(
                        key, json.dumps(record), xx=True
                    )
                    print("Record updated." if updated else
                          "Record no longer exists.")

                               # DELETE: Remove a specific record after confirmation.
                elif choice == "5":
                    confirmation = input(
                        f"Delete '{identifier}'? Type YES: "
                    ).strip()

                    if confirmation == "YES":
                        deleted = database.delete(key)
                        print("Record deleted." if deleted else
                              "Record not found.")
                    else:
                        print("Deletion canceled.")

            elif choice == "6":
                repository_ranking(database)

            elif choice == "7":
                    contributor_lookup(database)

            elif choice == "8":
                    language_breakdown(database)

            elif choice == "0":
                    print("Program ended.")
                    break

            else:
                print("Invalid menu selection.")

        except (redis.RedisError, OSError, ValueError,
                zipfile.BadZipFile, KeyError) as error:
            print(f"Operation failed: {error}")

def main():
    print("GitHub Activity Explorer")
    print("System date and time:",
          datetime.now().astimezone().isoformat(
              sep=" ", timespec="seconds"
          ))

    database = redis.Redis(
        host="127.0.0.1",
        port=6379,
        db=DATABASE_NUMBER,
        decode_responses=True
    )

    try:
        database.ping()
        print(f"Connected to Redis database {DATABASE_NUMBER}.")
        
        crud_menu(database)

    except (redis.RedisError, OSError, ValueError,
            zipfile.BadZipFile, KeyError) as error:
        print(f"Import failed: {error}")

    finally:
        database.close()


if __name__ == "__main__":
    main()