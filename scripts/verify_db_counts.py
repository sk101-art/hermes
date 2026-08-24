import sqlite3
import sys
import os

EXPECTED_COUNTS = {
    'events': 368,
    'story_clusters': 345,
    'claims': 360,
    'evidence': 416,
    'technology_assessments': 345,
    'projects': 2,
    'inbox_items': 322,
    'saved_items': 2,
    'daily_briefings': 1,
    'source_checkpoints': 9,
    'runtime_jobs': 10,
    'intelligence_changes': 0
}

def verify_counts(db_path='data/tech_intel.db', output_report='reports/db_row_counts.md'):
    if not os.path.exists(db_path):
        print(f"FAIL: Database file not found at {db_path}")
        sys.exit(1)

    os.makedirs(os.path.dirname(output_report) if os.path.dirname(output_report) else '.', exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    report = [
        '# Authoritative Database Row Counts',
        '',
        '| Table | Expected | Actual | Status |',
        '|---|---|---|---|'
    ]

    errors = []
    for table, expected in EXPECTED_COUNTS.items():
        try:
            actual = cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except Exception as e:
            actual = f"ERROR ({e})"
            errors.append(f"Table {table}: query error {e}")
            report.append(f"| {table} | {expected} | {actual} | ERROR |")
            continue

        status = 'MATCH' if actual == expected else 'MISMATCH'
        report.append(f"| {table} | {expected} | {actual} | {status} |")
        if actual != expected:
            errors.append(f"Table {table}: expected {expected}, got {actual}")

    with open(output_report, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report) + '\n')

    print('\n'.join(report))
    if errors:
        print("\nFATAL ERRORS:\n" + "\n".join(errors))
        sys.exit(1)

    print("\nPASS: All 12 authoritative database table counts verified.")

if __name__ == '__main__':
    db = sys.argv[1] if len(sys.argv) > 1 else 'data/tech_intel.db'
    out = sys.argv[2] if len(sys.argv) > 2 else 'reports/db_row_counts.md'
    verify_counts(db, out)
