import csv
import sqlite3
import argparse
import json
from collections import defaultdict
import pandas as pd


def parse_args():
    parser = argparse.ArgumentParser(description="FitNotes Data Importer")
    parser.add_argument("--csv", default="FitNotes_Export_note20.csv")
    parser.add_argument("--db", default="FitNotes_Backup.fitnotes")
    parser.add_argument("--map", default="ex_mapping_table.csv")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-json", action="store_true")
    return parser.parse_args()


def load_mapping(mapping_file):
    mapping = []
    with open(mapping_file, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            mapping.append(row)
    return mapping


def log_message(logs, level, message):
    logs.append({"level": level, "message": message})


def get_existing_exercises(conn):
    cur = conn.cursor()
    cur.execute("SELECT name, category_id FROM exercise")
    return {row[0]: row[1] for row in cur.fetchall()}


def get_category_map(conn):
    cur = conn.cursor()
    cur.execute("SELECT _id, name FROM category")
    return {name: _id for _id, name in cur.fetchall()}


def insert_category(conn, name, dry_run, logs):
    log_message(logs, "info", f"Creating missing category: {name}")
    if not dry_run:
        cur = conn.cursor()
        cur.execute("INSERT INTO category (name) VALUES (?)", (name,))
        conn.commit()


def rename_exercise(conn, old_name, new_name, dry_run, logs):
    log_message(logs, "info", f"Renaming exercise '{old_name}' -> '{new_name}'")
    if not dry_run:
        cur = conn.cursor()
        cur.execute("UPDATE exercise SET name = ? WHERE name = ?", (new_name, old_name))
        conn.commit()


def insert_exercise(conn, name, category_id, dry_run, logs):
    log_message(logs, "info", f"Inserting new exercise: {name} in category {category_id}")
    if not dry_run:
        cur = conn.cursor()
        cur.execute("INSERT INTO exercise (name, category_id, weight_unit_id) VALUES (?, ?, 0)", (name, category_id))
        conn.commit()


def process_mappings(conn, mapping, dry_run, logs, export):
    existing_exercises = get_existing_exercises(conn)
    category_map = get_category_map(conn)
    for row in mapping:
        recommendation = row["my_recommendation"].strip()
        csv_name = row["csv"].strip()
        backup_name = row["backup"].strip() if row["backup"] else None
        if recommendation == "new_ex":
            if csv_name in existing_exercises:
                log_message(logs, "warning", f"Exercise '{csv_name}' already exists, but marked as new_ex")
            # cat_name = infer_category_from_name(csv_name)
            cat_name = row["category"]
            if cat_name not in category_map:
                insert_category(conn, cat_name, dry_run, logs)
                category_map = get_category_map(conn)
            insert_exercise(conn, csv_name, category_map[cat_name], dry_run, logs)
            #update the existing exercises
            existing_exercises = get_existing_exercises(conn)

        elif recommendation == "rename_backup":
            if backup_name not in existing_exercises:
                log_message(logs, "warning", f"Cannot rename: backup name '{backup_name}' does not exist")
            else:
                rename_exercise(conn, backup_name, csv_name, dry_run, logs)
                #update the existing exercises
                existing_exercises = get_existing_exercises(conn)

        elif recommendation == "rename_csv":
            # if csv_name not in existing_exercises:
            #     log_message(logs, "warning", f"Cannot rename: csv name '{csv_name}' does not exist")
            # else:
            #     rename_exercise(conn, csv_name, backup_name, dry_run, logs)
            export.loc[export["exercise"] == row["csv"], "exercise"] = row["backup"]
        else:
            log_message(logs, "warning", f"Unknown recommendation type: {recommendation} for '{csv_name}'")

        if not backup_name and recommendation != "new_ex":
            log_message(logs, "warning", f"Empty backup value for '{csv_name}' but recommendation is not 'new_ex'")
    return export


def main():
    args = parse_args()
    logs = []
    conn = sqlite3.connect(args.db)
    #TODO: not the most memory friendly thing to do here. But didn't want to do all the fiddling with find and replace manually
    #TODO: find out why they used csv instead of pandas. Maybe because csv is built-in?
    export = pd.read_csv(args.csv)
    print(f"rows in export: {len(export)}")
    try:
        mapping = load_mapping(args.map)
        export = process_mappings(conn, mapping, args.dry_run, logs, export)
        #insert training logs and comments

    finally:
        conn.close()

    if args.log_json:
        with open("exercise_migration_log.json", "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=2, ensure_ascii=False)
    else:
        for entry in logs:
            print(f"[{entry['level'].upper()}] {entry['message']}")


if __name__ == "__main__":
    main()
