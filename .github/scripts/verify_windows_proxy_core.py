"""Reject a Windows proxy-core run whose native Mihomo cases did not really run."""
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

# These start the bundled Mihomo build itself; a missing binary would skip them.
REQUIRED = (
    "test_real_core_two_independent_upstreams_and_no_direct_fallback",
    "test_real_core_refuses_an_occupied_listener_port_and_reaps_its_processes",
    "test_real_core_close_stops_it_and_removes_its_working_directory",
    "test_real_core_exits_when_its_backend_is_killed",
    "test_listener_check_never_adopts_a_port_held_by_another_local_service",
)
# Guard checks that use a shell-script stand-in for Mihomo and POSIX signals.
POSIX_ONLY = (
    "test_guard_gives_the_core_its_config_and_removes_its_directory_on_close",
    "test_guard_kills_a_core_that_ignores_terminate",
    "test_killed_backend_leaves_no_core_behind",
    "test_core_that_exits_at_startup_fails_fast_and_is_not_restarted_by_the_guard",
    "test_guard_without_a_config_never_starts_the_core",
)


def main() -> int:
    errors = []
    if sys.platform != "win32":
        errors.append("This check needs a real Windows interpreter")
    cases = []
    for report in sys.argv[1:]:
        try:
            cases += list(ET.parse(report).getroot().iter("testcase"))
        except (OSError, ET.ParseError) as exc:
            errors.append(f"JUnit report unavailable: {report}: {exc}")
    outcome = {}
    for case in cases:
        name = case.get("name", "")
        state = "skipped" if case.find("skipped") is not None else "failed" if any(
            case.find(tag) is not None for tag in ("failure", "error")) else "passed"
        if name in outcome:
            errors.append(f"Case reported twice: {name}")
        outcome[name] = state
    for name in REQUIRED:
        if outcome.get(name) != "passed":
            errors.append(f"Required native case did not pass: {name} ({outcome.get(name, 'absent')})")
    for name, state in sorted(outcome.items()):
        if state == "failed":
            errors.append(f"Failed: {name}")
        elif state == "skipped" and name not in POSIX_ONLY:
            errors.append(f"Unexpected skip: {name}")
    passed = sum(state == "passed" for state in outcome.values())
    print(f"{passed} passed, {len(outcome) - passed} not passed, {len(REQUIRED)} native cases required")
    for error in errors:
        print("ERROR:", error)
    return 1 if errors or not cases else 0


if __name__ == "__main__":
    sys.exit(main())
