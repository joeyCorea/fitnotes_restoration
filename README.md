# Because your workout history is more than just data — it’s your story.

In March 2025, my phone died unexpectedly.

No big deal, I thought. After all, I’d been exporting my workout logs from FitNotes _every_ week. But what I didn’t realize was this:

**An export is _not_ a backup.**

Five years of meticulously logged training — gone. All my personal records, all my progress, all the subtle cues and trends that kept me pushing forward. I rely on numbers to stay motivated, to know what "better" looks like. Without that data, every workout felt like it started from zero.

That’s when I decided:
If the app won’t let me restore, I’ll build the restore myself.

This project is the result — a pipeline that turns a humble CSV export into a full-fledged FitNotes backup, ready to be restored directly into the app. It parses and transforms, maps and merges, re-creates exercises and training logs, and even restores your notes. In short:

_It puts your training history back where it belongs — in your hands._

# This is what I was working with

## 1. CSV Export: FitNotes_Export_note20.csv

| Column        | Type   | Used In                    | Description / Notes                                                                 |
|---------------|--------|----------------------------|-------------------------------------------------------------------------------------|
| Date          | str    | training_log.date          | Format: YYYY-MM-DD; converted to datetime                                           |
| Exercise      | str    | exercise.name              | Name as logged in export; mapped or renamed via mapping                             |
| Category      | str    | (not used)                 | Present in original export, currently ignored. However, can be linked to exercise for completeness  |
| Weight        | float  | training_log.metric_weight | Parsed with fallback to 0.0 if invalid/NaN                                          |
| Reps          | int    | training_log.reps          | Guarded with fallback to 0.0                                                        |
| Distance      | float  | training_log.distance      | 0.0 if blank/invalid; used only for cardio exercises                                |
| Time          | str    | training_log.duration_seconds | Format: HH:MM:SS; converted to seconds                                         |
| Weight Unit   | int    | training_log.unit          | Hardcoded: 0 for resistance, 2 for running                                          |
| Comment       | str    | Comment.comment            | Only inserted if not blank/null/NaN                                                 |

---

## 2. Mapping Table: ex_mapping_table.csv

| Column           | Type   | Used In             | Description / Notes                                                         |
|------------------|--------|---------------------|-----------------------------------------------------------------------------|
| my_recommendation| str    | process_mappings()  | One of: new_ex, rename_backup, rename_csv                                   |
| csv              | str    | export["Exercise"]  | Exercise name from the CSV                                                  |
| backup           | str?   | exercise.name       | Exercise name from backup DB                                                |
| category         | str    | exercise.category_id| Required for new_ex to create or assign categories                          |
| Confidence       | str    | (not used)          | Optional metadata for auditing (High/Medium/Low)                            |
| Notes            | str    | (not used)          | Human notes; helpful for logging or manual review                           |

**Special handling:**
- If `my_recommendation` is `new_ex` but the csv name already exists, a warning is logged.
- If backup is empty but recommendation is not `new_ex`, a warning is logged.
- `rename_csv` updates the CSV in-memory using pandas (before DB write).

---

## 3. SQLite Database: FitNotes_Backup.fitnotes

### exercise Table

| Column         | Type  | Description                                |
|----------------|-------|--------------------------------------------|
| name           | TEXT  | Exercise name                              |
| category_id    | INT   | FK to category._id                         |
| weight_unit_id | INT   | 0 for kg/lbs, 2 for distance (manual)      |

### category Table

| Column | Type | Description      |
|--------|------|-----------------|
| _id    | INT  | PK              |
| name   | TEXT | Category name   |

### training_log Table

| Column                        | Type  | Description / Notes                                 |
|-------------------------------|-------|-----------------------------------------------------|
| date                          | TEXT  | Set to YYYY-MM-DD (from CSV)                        |
| exercise_id                   | INT   | FK to exercise._id                                  |
| metric_weight                 | REAL  | From CSV Weight                                     |
| reps                          | REAL  | From CSV Reps, coerced                              |
| unit                          | INT   | 0 = weight, 2 = distance (manual rule)              |
| routine_section_exercise_set_id| INT  | Always 0                                            |
| timer_auto_start              | INT   | Always 0                                            |
| is_personal_record            | INT   | Always 0                                            |
| is_personal_record_first      | INT   | Always 0                                            |
| is_complete                   | INT   | Always 0                                            |
| is_pending_update             | INT   | Always 0                                            |
| distance                      | REAL  | Parsed from CSV; default 0.0                        |
| duration_seconds              | INT   | Parsed from Time string                             |

### Comment Table

| Column        | Type | Description                       |
|---------------|------|-----------------------------------|
| date          | TEXT | Matches training_log.date         |
| owner_type_id | INT  | Always 1 for training log         |
| owner_id      | INT  | FK to training_log._id            |
| comment       | TEXT | From Comment column in CSV        |
