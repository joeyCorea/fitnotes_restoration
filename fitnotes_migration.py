import csv
import sqlite3
import argparse
import json
from datetime import datetime as dt
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

def time_to_seconds(time_str):
    if isinstance(time_str, str):
        try:
            # Split the string by ":"
            hours, minutes, seconds = map(int, time_str.split(':'))
            # Convert to total seconds
            return hours * 3600 + minutes * 60 + seconds
        except ValueError:
            return None  # Return None if the string format is incorrect

import math

def guard_against_null(raw_val) -> float:
    try:
        val = float(raw_val)
        if math.isnan(val):
            return 0.0
        else:
            return val
    except (ValueError, TypeError):
        return 0.0

def insert_training_log(conn, row, logs):
    #TODO: this method has become quite the monolith, see if I can split it up.
    log_message(logs, "info", f"Inserting log for {row.get('Date')}")
    
    required = ["Date", "Exercise", "Weight", "Reps", "Weight Unit", "Distance", "Time"]
    missing = [k for k in required if k not in row or row[k] in (None, "", "null")]
    if missing:
        log_message(logs, "error", f"Missing required fields: {missing}")
        return

    try:
        comment_date = dt.strptime(row["Date"], "%Y-%m-%d")
        comment_date_str = comment_date.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        log_message(logs, "error", f"Invalid date format: {row['Date']}")
        return

    duration = time_to_seconds(row["Time"])
    if duration is None:
        duration = 0  # or another appropriate default

    #TODO: move these to the guard_against helper
    try:
        distance = float(row["Distance"])
        if math.isnan(distance):
            distance = 0.0
    except (ValueError, TypeError):
        distance = 0.0

    try:
        weight = float(row["Weight"])
        if math.isnan(weight):
            weight = 0.0
    except (ValueError, TypeError):
        weight = 0.0

    reps = guard_against_null(row["Reps"])

    log_values = (
        row["Date"], weight, reps, row["Weight Unit"], distance, duration
    )
    insert_log = """
    INSERT INTO training_log (
        date, exercise_id, metric_weight, reps, unit,
        routine_section_exercise_set_id, timer_auto_start, is_personal_record, 
        is_personal_record_first, is_complete, is_pending_update, distance, duration_seconds
    )
    SELECT 
        ?, 
        e._id, 
        ?, ?, ?, 
        0, 0, 0, 0, 0, 0, 
        ?, ?
    FROM exercise e
    WHERE e.name = ?
    RETURNING _id
    """

    insert_comment = """
    INSERT INTO Comment (
        date, owner_type_id, owner_id, comment
    ) VALUES (?, ?, ?, ?)
    """
    try:
        cur = conn.cursor()
        cur.execute(insert_log, (*log_values, row["Exercise"]))
        result = cur.fetchone()
        if result is None:
            raise RuntimeError(f"No ID returned from insert_log; maybe {row['Exercise']} exercise not found?")
        new_log_id = result[0]
        comment_text = row.get("Comment")
        if comment_text is not None:
            if isinstance(comment_text, float) and math.isnan(comment_text):
                comment_text = ""
            else:
                comment_text = str(comment_text).strip()
        if comment_text not in ("", "null"):
            comment_values = (comment_date_str, 1, new_log_id, comment_text)
            cur.execute(insert_comment, comment_values)
        cur.close()
        conn.commit()
    except Exception as e:
        conn.rollback()
        log_message(logs, "error", f"Error inserting training log: {e}")



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
            log_message(logs, "info", f"Renaming csv for {row['csv']} to {row['backup']}")
            export.loc[export["Exercise"] == row["csv"], "Exercise"] = row["backup"]
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
    export = pd.read_csv(args.csv)
    print(f"rows in export: {len(export)}")
    try:
        mapping = load_mapping(args.map)
        export = process_mappings(conn, mapping, args.dry_run, logs, export)
        #weight unit hard-coding
        export.loc[export["Exercise"].str.contains("Running"), "Weight Unit"] = 2
        export.loc[~(export["Exercise"].str.contains("Running")), "Weight Unit"] = 0
        #insert training logs and comments
        for row in export.to_dict(orient='records'):
            insert_training_log(conn, row, logs)
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
