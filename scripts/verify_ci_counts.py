import xml.etree.ElementTree as ET
import sys
import os

def check_junit(xml_path, expected_total, name):
    if not os.path.exists(xml_path):
        print(f"FAIL: {name} report not found at {xml_path}")
        sys.exit(1)
    
    tree = ET.parse(xml_path)
    root = tree.getroot()
    
    if root.tag == 'testsuites':
        total_tests = sum(int(ts.attrib.get('tests', 0)) for ts in root.findall('testsuite'))
        failures = sum(int(ts.attrib.get('failures', 0)) for ts in root.findall('testsuite'))
        errors = sum(int(ts.attrib.get('errors', 0)) for ts in root.findall('testsuite'))
        skipped = sum(int(ts.attrib.get('skipped', 0)) for ts in root.findall('testsuite'))
    else:
        total_tests = int(root.attrib.get('tests', 0))
        failures = int(root.attrib.get('failures', 0))
        errors = int(root.attrib.get('errors', 0))
        skipped = int(root.attrib.get('skipped', 0))
        
    print(f"[{name}] Total: {total_tests} (expected {expected_total}), Failures: {failures}, Errors: {errors}, Skipped: {skipped}")
    
    if total_tests != expected_total:
        print(f"FAIL: {name} total tests {total_tests} != expected {expected_total}")
        sys.exit(1)
    if failures > 0 or errors > 0:
        print(f"FAIL: {name} has {failures} failures and {errors} errors")
        sys.exit(1)
    if skipped > 0:
        print(f"FAIL: {name} has {skipped} skipped tests (no skipped tests allowed)")
        sys.exit(1)
    print(f"PASS: {name} exact count ({total_tests}) and pass rate verified.")

if __name__ == '__main__':
    if len(sys.argv) < 4:
        print("Usage: verify_ci_counts.py [xml_path] [expected_count] [suite_name]")
        sys.exit(1)
    check_junit(sys.argv[1], int(sys.argv[2]), sys.argv[3])
