import re
import sys
import os

def check_frontend(log_path, expected_count=222):
    if not os.path.exists(log_path):
        print(f"FAIL: Frontend test log not found at {log_path}")
        sys.exit(1)

    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    tests_match = re.search(r'tests\s+(\d+)', content)
    pass_match = re.search(r'pass\s+(\d+)', content)
    fail_match = re.search(r'fail\s+(\d+)', content)
    skipped_match = re.search(r'skipped\s+(\d+)', content)

    if not (tests_match and pass_match and fail_match):
        print("FAIL: Could not parse test summary numbers from frontend test log")
        sys.exit(1)

    tests = int(tests_match.group(1))
    passed = int(pass_match.group(1))
    failed = int(fail_match.group(1))
    skipped = int(skipped_match.group(1)) if skipped_match else 0

    print(f"[Frontend Unit Suite] Total: {tests} (expected {expected_count}), Pass: {passed}, Fail: {failed}, Skipped: {skipped}")

    if tests != expected_count:
        print(f"FAIL: Total frontend tests {tests} != expected {expected_count}")
        sys.exit(1)
    if passed != expected_count or failed > 0:
        print(f"FAIL: Expected {expected_count} passed, got {passed} passed and {failed} failed")
        sys.exit(1)
    if skipped > 0:
        print(f"FAIL: {skipped} skipped tests in frontend suite (no skips allowed)")
        sys.exit(1)

    print(f"PASS: Frontend test count ({tests}) and 100% pass rate verified.")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: verify_frontend_counts.py <log_path> [expected_count]")
        sys.exit(1)
    expected = int(sys.argv[2]) if len(sys.argv) > 2 else 222
    check_frontend(sys.argv[1], expected)
