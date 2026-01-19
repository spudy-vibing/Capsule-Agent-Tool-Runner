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
"""

# Public API will be exposed here as report module is implemented
__all__: list[str] = []
