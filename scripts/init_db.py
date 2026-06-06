from pathlib import Path
import sqlite3


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "runforfan.sqlite"
SCHEMA_PATH = DATA_DIR / "schema.sql"
SEED_PATH = DATA_DIR / "seed.sql"


def execute_script(connection: sqlite3.Connection, path: Path) -> None:
    connection.executescript(path.read_text(encoding="utf-8"))


def table_count(connection: sqlite3.Connection, table_name: str) -> int:
    cursor = connection.execute(f"SELECT COUNT(*) FROM {table_name}")
    return int(cursor.fetchone()[0])


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    with sqlite3.connect(DB_PATH) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        execute_script(connection, SCHEMA_PATH)
        execute_script(connection, SEED_PATH)

        counts = {
            "screenshot_sources": table_count(connection, "screenshot_sources"),
            "training_activities": table_count(connection, "training_activities"),
            "activity_segments": table_count(connection, "activity_segments"),
            "activity_split_blocks": table_count(connection, "activity_split_blocks"),
            "lactate_threshold_measurements": table_count(connection, "lactate_threshold_measurements"),
            "import_batches": table_count(connection, "import_batches"),
            "running_goals": table_count(connection, "running_goals"),
        }

    print(f"Created {DB_PATH}")
    for table_name, count in counts.items():
        print(f"{table_name}: {count}")


if __name__ == "__main__":
    main()
