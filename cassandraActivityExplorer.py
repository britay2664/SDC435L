from collections import Counter

import io
import json
import zipfile
from pathlib import Path



# Name: Brian Taylor
# Date: October 19, 2026
# Assignment: SDC435L Course Project Week 3
# Purpose: Connect to Cassandra for the GitHub Activity Explorer project.
# Dataset import, interactive CRUD, and analysis will be added next.

from datetime import datetime
from getpass import getpass

from cassandra.auth import PlainTextAuthProvider
from cassandra.cluster import Cluster


KEYSPACE = "sdc435l_github_archive"

DATASET_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "GitHubArchive-Dataset.zip"
)
IMPORT_LIMIT = 5000

def create_tables(session):
    """Create tables organized around the application's queries."""

    session.execute("""
        CREATE TABLE IF NOT EXISTS repositories (
            repo_name text PRIMARY KEY,
            watch_count bigint
        )
    """)

    session.execute("""
        CREATE TABLE IF NOT EXISTS commits (
            commit_id text PRIMARY KEY,
            author_name text,
            repo_names list<text>,
            message text,
            subject text
        )
    """)

    session.execute("""
        CREATE TABLE IF NOT EXISTS languages (
            repo_name text PRIMARY KEY,
            language_bytes map<text, bigint>
        )
    """)

    # A separate table supports author lookups by partition key.
    # The application will maintain it when commits change.
    session.execute("""
        CREATE TABLE IF NOT EXISTS commits_by_author (
            author_name text,
            commit_id text,
            repo_names list<text>,
            subject text,
            PRIMARY KEY (author_name, commit_id)
        )
    """)

    print("All four project tables are ready.")

def read_dataset_records(archive, filename):
    """Stream the first 5,000 nonblank JSON records from a ZIP member."""
    count = 0

    with archive.open(filename) as source:
        with io.TextIOWrapper(source, encoding="utf-8") as lines:
            for line_number, line in enumerate(lines, start=1):
                if not line.strip():
                    continue

                try:
                    record = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        f"{filename}, line {line_number}: invalid JSON"
                    ) from error

                if not isinstance(record, dict):
                    raise ValueError(
                        f"{filename}, line {line_number}: expected an object"
                    )

                yield record
                count += 1

                if count >= IMPORT_LIMIT:
                    break


def save_commit(session, statements, record):
    """Maintain the main commit table and its author lookup table."""

    commit_id = record.get("commit")
    if not isinstance(commit_id, str) or not commit_id.strip():
        raise ValueError("Commit record is missing a valid commit hash.")

    author = record.get("author")
    author_name = author.get("name") if isinstance(author, dict) else None

    # Cassandra partition keys cannot be empty.
    # Group missing author names under an explicit label.
    if not isinstance(author_name, str) or not author_name.strip():
        author_name = "(Unknown author)"
    repo_names = record["repo_name"]
    message = record["message"]
    subject = record.get("subject", "")

    # Remove the old lookup entry if an existing commit changes author.
    existing = session.execute(
        statements["find_commit"], (commit_id,)
    ).one()

    if (
        existing is not None
        and existing.author_name
        and existing.author_name != author_name
    ):
        session.execute(
            statements["delete_author_commit"],
            (existing.author_name, commit_id),
        )

    session.execute(
        statements["insert_commit"],
        (commit_id, author_name, repo_names, message, subject),
    )

    session.execute(
        statements["insert_author_commit"],
        (author_name, commit_id, repo_names, subject),
    )


def prepare_statements(session):
    """Prepare parameterized CQL statements for repeated operations."""
    queries = {
        "insert_repo": """
            INSERT INTO repositories (repo_name, watch_count)
            VALUES (?, ?)
        """,
        "insert_language": """
            INSERT INTO languages (repo_name, language_bytes)
            VALUES (?, ?)
        """,
        "find_commit": """
            SELECT author_name FROM commits WHERE commit_id = ?
        """,
        "insert_commit": """
            INSERT INTO commits
                (commit_id, author_name, repo_names, message, subject)
            VALUES (?, ?, ?, ?, ?)
        """,
        "insert_author_commit": """
            INSERT INTO commits_by_author
                (author_name, commit_id, repo_names, subject)
            VALUES (?, ?, ?, ?)
        """,
        "delete_author_commit": """
            DELETE FROM commits_by_author
            WHERE author_name = ? AND commit_id = ?
        """,
    }

    return {
        name: session.prepare(query)
        for name, query in queries.items()
    }


def import_dataset(session, statements):
    """Import sample records without extracting the large ZIP."""
    if not DATASET_PATH.is_file():
        raise FileNotFoundError(f"Dataset not found: {DATASET_PATH}")

    with zipfile.ZipFile(DATASET_PATH) as archive:
        filename = "GitHubArchive-Dataset/Sample_Repos.json"
        count = 0

        for record in read_dataset_records(archive, filename):
            watch_count = int(record["watch_count"])
            if watch_count < 0:
                raise ValueError("Watch counts cannot be negative.")

            session.execute(
                statements["insert_repo"],
                (record["repo_name"], watch_count),
            )
            count += 1

        print(f"Sample_Repos.json: processed {count:,} records.", flush=True)

        filename = "GitHubArchive-Dataset/Commits.json"
        count = 0

        for record in read_dataset_records(archive, filename):
            save_commit(session, statements, record)
            count += 1

            if count % 1000 == 0:
                print(f"Commits: {count:,} processed...", flush=True)

        print(f"Commits.json: processed {count:,} records.", flush=True)

        filename = "GitHubArchive-Dataset/Languages.json"
        count = 0

        for record in read_dataset_records(archive, filename):
            language_bytes = {}

            for language in record["language"]:
                byte_count = int(language["bytes"])
                if byte_count < 0:
                    raise ValueError("Language byte counts cannot be negative.")

                name = language["name"]
                language_bytes[name] = (
                    language_bytes.get(name, 0) + byte_count
                )

            session.execute(
                statements["insert_language"],
                (record["repo_name"], language_bytes),
            )
            count += 1

        print(f"Languages.json: processed {count:,} records.", flush=True)

    print("Import complete. Matching primary keys were updated.")
    print("Each imported commit also has an author lookup entry.")
    print("Results describe only the imported historical sample.")

def ask_repository_name():
    """Validate the repository identifier."""
    name = input("Repository name (owner/name): ").strip()
    parts = name.split("/")

    if len(parts) != 2 or not all(part.strip() for part in parts):
        raise ValueError("Enter a repository name such as britay2664/demo.")

    return name


def ask_watch_count():
    """Accept a nonnegative count that fits Cassandra's bigint type."""
    count = int(input("Watch count: ").strip())

    if not 0 <= count <= 9223372036854775807:
        raise ValueError("Enter a nonnegative 64-bit integer.")

    return count


def create_repository(session):
    """CREATE: Insert only if the repository does not already exist."""
    name = ask_repository_name()
    count = ask_watch_count()

    result = session.execute(
        """
        INSERT INTO repositories (repo_name, watch_count)
        VALUES (%s, %s) IF NOT EXISTS
        """,
        (name, count),
    ).one()

    print("Repository created." if result.applied
          else "Repository already exists. Use Update instead.")


def read_repository(session):
    """READ: Retrieve a repository using its primary key."""
    name = ask_repository_name()

    record = session.execute(
        """
        SELECT repo_name, watch_count
        FROM repositories WHERE repo_name = %s
        """,
        (name,),
    ).one()

    if record is None:
        print("Repository not found.")
    else:
        print(json.dumps({
            "repo_name": record.repo_name,
            "watch_count": record.watch_count,
        }, indent=2))


def update_repository(session):
    """UPDATE: Change the count only if the repository exists."""
    name = ask_repository_name()
    count = ask_watch_count()

    result = session.execute(
        """
        UPDATE repositories SET watch_count = %s
        WHERE repo_name = %s IF EXISTS
        """,
        (count, name),
    ).one()

    print("Repository updated." if result.applied
          else "Repository not found.")


def delete_repository(session):
    """DELETE: Remove a repository after explicit confirmation."""
    name = ask_repository_name()

    if input(f"Delete '{name}'? Type YES: ").strip() != "YES":
        print("Deletion canceled.")
        return

    result = session.execute(
        "DELETE FROM repositories WHERE repo_name = %s IF EXISTS",
        (name,),
    ).one()

    print("Repository deleted." if result.applied
          else "Repository not found.")
def repository_commit_ranking(session):
    """Count stored commits associated with each repository."""
    counts = Counter()
    total = 0

    # This sample-wide analysis scans commits; it is intended for the lab.
    for record in session.execute("SELECT repo_names FROM commits"):
        total += 1
        # Count a commit once per repository, even if its list repeats a name.
        counts.update(set(record.repo_names or []))

    if not counts:
        print("No repository commit associations found.")
        return

    print("\nTop 10 repositories by stored commit count")
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))

    for rank, (name, count) in enumerate(ranked[:10], start=1):
        print(f"{rank}. {name}: {count:,} commits")

    print(f"Stored commits scanned: {total:,}")
    print("A commit may be associated with multiple repositories.")
    print("These are sample counts, not current trends or a timeline.")


def contributor_lookup(session):
    """Query the author partition directly without scanning all commits."""
    name = input(
        "Author's exact name, or (Unknown author): "
    ).strip()

    if not name:
        raise ValueError("Enter an author name.")

    records = session.execute(
        """
        SELECT commit_id, repo_names, subject
        FROM commits_by_author WHERE author_name = %s
        """,
        (name,),
    )

    total = 0
    print(f"\nStored commits by {name}")

    for record in records:
        total += 1

        if total <= 20:
            print(f"\nCommit: {record.commit_id}")
            print("Repositories:", ", ".join(record.repo_names or []))
            subject = " ".join((record.subject or "").split())
            print("Subject:", subject[:150])

    print(f"\nTotal matching commits: {total:,}")

    if total > 20:
        print("Only the first 20 matches are displayed.")

    print("Names are case-sensitive and may be shared by different people.")
    print("Results cover stored data and are not chronological.")


def repository_language_breakdown(session):
    """Retrieve a repository's language map using its primary key."""
    name = ask_repository_name()

    record = session.execute(
        """
        SELECT language_bytes FROM languages WHERE repo_name = %s
        """,
        (name,),
    ).one()

    if record is None:
        print("Language record not found.")
        return

    languages = record.language_bytes or {}
    total = sum(languages.values())

    if total <= 0:
        print("No positive language byte total is available.")
        return

    print(f"\nLanguage breakdown for {name}")

    for language, byte_count in sorted(
        languages.items(), key=lambda item: (-item[1], item[0])
    ):
        print(f"{language}: {byte_count:,} bytes ({byte_count / total:.1%})")

    print(f"Total recorded bytes: {total:,}")
    print("Results describe the imported historical record.")

def menu(session, statements):
    """Let the user choose an operation without importing at startup."""
    while True:
        print("\nCassandra GitHub Activity Explorer")
        print("System date and time:",
              datetime.now().astimezone().isoformat(timespec="seconds"))
        print("1. Import dataset")
        print("0. Exit")

        choice = input("Select an option: ").strip()

        if choice == "1":
            try:
                import_dataset(session, statements)
            except Exception as error:
                print(f"Import failed: {error}")
                print("Earlier writes may already have been saved.")

        elif choice == "0":
            print("Program ended.")
            return

        else:
            print("Choose 1 or 0.")

def menu(session, statements):
    """Route menu choices to import and repository CRUD operations."""
    actions = {
        "1": lambda: import_dataset(session, statements),
        "2": lambda: create_repository(session),
        "3": lambda: read_repository(session),
        "4": lambda: update_repository(session),
        "5": lambda: delete_repository(session),
        "6": lambda: repository_commit_ranking(session),
        "7": lambda: contributor_lookup(session),
        "8": lambda: repository_language_breakdown(session),
    }

    while True:
        print("\nCassandra GitHub Activity Explorer")
        print("System date and time:",
              datetime.now().astimezone().isoformat(timespec="seconds"))
        print("1. Import dataset")
        print("2. Create a repository")
        print("3. Read a repository")
        print("4. Update a repository")
        print("5. Delete a repository")
        print("6. Rank repositories by commit count")
        print("7. Look up commits by author")
        print("8. View language breakdown for a repository")
        print("0. Exit")

        choice = input("Select an option: ").strip()

        if choice == "0":
            print("Program ended.")
            return

        action = actions.get(choice)

        if action is None:
            print("Choose an option from 0 through 8.")
            continue

        try:
            action()
        except Exception as error:
            print(f"Operation failed: {error}")
            if choice == "1":
                print("Earlier import writes may already have been saved.")

def main():
    cluster = None

    print("Cassandra GitHub Activity Explorer")
    print("System date and time:",
          datetime.now().astimezone().isoformat(timespec="seconds"))

    username = input("Cassandra username: ").strip()
    password = getpass("Cassandra password: ")

    try:
        # Authenticate without storing credentials in the source code.
        authentication = PlainTextAuthProvider(
            username=username,
            password=password,
        )

        cluster = Cluster(
            ["127.0.0.1"],
            port=9042,
            auth_provider=authentication,
        )
        session = cluster.connect()
        print("Authenticated connection successful!")

        # This replication configuration is for a local, single-node lab.
        session.execute(f"""
            CREATE KEYSPACE IF NOT EXISTS {KEYSPACE}
            WITH replication = {{
                'class': 'SimpleStrategy',
                'replication_factor': 1
            }}
        """)

        session.set_keyspace(KEYSPACE)
        print(f"Project keyspace ready: {KEYSPACE}")

        create_tables(session)
        statements = prepare_statements(session)
        menu(session, statements)

    finally:
        if cluster is not None:
            cluster.shutdown()


if __name__ == "__main__":
    main()