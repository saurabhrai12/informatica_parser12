"""Informatica → Snowflake function translation dictionary.

Agent-modifiable: extend, never remove existing entries. Each value is a
callable or a format string with positional placeholders {0}, {1}, ...
"""

INFA_TO_SF: dict[str, str] = {
    "IIF":         "CASE WHEN {0} THEN {1} ELSE {2} END",
    "DECODE":      "CASE {0} {rest} END",            # special handling in generator
    "NVL":         "COALESCE({0}, {1})",
    "NVL2":        "IFF({0} IS NOT NULL, {1}, {2})",
    "SUBSTR":      "SUBSTRING({0}, {1}, {2})",
    "INSTR":       "POSITION({1} IN {0})",
    "TO_DATE":     "TO_DATE({0}, {1})",
    "TO_CHAR":     "TO_VARCHAR({0}, {1})",
    "SYSDATE":     "CURRENT_TIMESTAMP()",
    "TRUNC":       "DATE_TRUNC('DAY', {0})",
    "ADD_TO_DATE": "DATEADD({1}, {2}, {0})",
    "DATE_DIFF":   "DATEDIFF({2}, {1}, {0})",
    "LTRIM":       "LTRIM({0})",
    "RTRIM":       "RTRIM({0})",
    "LENGTH":      "LENGTH({0})",
    "UPPER":       "UPPER({0})",
    "LOWER":       "LOWER({0})",
}


def translate(infa_fn: str) -> str | None:
    return INFA_TO_SF.get(infa_fn.upper())
