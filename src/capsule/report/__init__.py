"""
Reporting module for Capsule.

This module generates human-readable and machine-readable reports
from completed runs.

Output formats:
    - Console: Rich terminal output with timeline and status icons
    - JSON: Structured output for programmatic consumption

Console report includes:
    - Timeline view of all tool calls
    - Status icons (success, error, denied)
    - Summary statistics:
        - Files accessed (read/write)
        - Domains contacted
        - Shell commands run
        - Total duration
        - Policy denials count

JSON report includes:
    - Full run metadata
    - All tool calls with arguments
    - All results with timing
    - Policy decisions with reasons

Example:
    from capsule.report import generate_console_report, generate_json_report

    # Console report
    generate_console_report("abc123", "capsule.db")

    # JSON report
    json_str = generate_json_report("abc123", "capsule.db")
    print(json_str)
"""

from capsule.report.console import generate_console_report
from capsule.report.json import build_report_dict, generate_json_report

__all__ = [
    "generate_console_report",
    "generate_json_report",
    "build_report_dict",
]
