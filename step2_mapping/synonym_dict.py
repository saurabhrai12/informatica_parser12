"""Domain abbreviation + synonym dictionary for Step 2 column matching.

Agent-modifiable: extend, never remove. See CLAUDE.md and
mapping_identification.txt §"SEMANTIC MATCHING RULES".
"""

ABBREV: dict[str, str] = {
    "AMT": "AMOUNT", "QTY": "QUANTITY", "DT": "DATE", "CD": "CODE",
    "DESC": "DESCRIPTION", "NBR": "NUMBER", "NO": "NUMBER", "TYP": "TYPE",
    "IND": "INDICATOR", "ADDR": "ADDRESS", "CUST": "CUSTOMER",
    "ACCT": "ACCOUNT", "TXN": "TRANSACTION", "BAL": "BALANCE",
    "EFF": "EFFECTIVE", "EXP": "EXPIRY", "SRC": "SOURCE", "TGT": "TARGET",
    "STR": "START", "CRT": "CREATED", "UPD": "UPDATED", "DEL": "DELETED",
    "FLG": "FLAG", "SEQ": "SEQUENCE", "REF": "REFERENCE", "CAT": "CATEGORY",
    "ID": "IDENTIFIER", "PK": "PRIMARY_KEY", "FK": "FOREIGN_KEY",
    "DIM": "DIMENSION", "FCT": "FACT", "STG": "STAGING", "AGG": "AGGREGATE",
    "ALERT": "ALERT", "RISK": "RISK_SCORE", "SAR": "SAR_FLAG",
    "STRCT": "STRUCTURING", "FRAUD": "FRAUD_INDICATOR",
}

SYNONYMS: list[set[str]] = [
    {"CREATED_DATE", "CREATION_DATE", "CREATE_DT", "INSERT_DATE", "LOAD_DATE", "INS_DT"},
    {"MODIFIED_DATE", "UPDATE_DATE", "LAST_UPDATED", "LAST_MODIFIED_DT", "UPD_DT"},
    {"STATUS", "STATE", "STATUS_CD", "RECORD_STATUS", "STAT"},
    {"EFFECTIVE_DATE", "EFF_DT", "START_DATE", "VALID_FROM", "EFF_FROM"},
    {"EXPIRY_DATE", "EXP_DT", "END_DATE", "VALID_TO", "EFF_TO"},
    {"CUSTOMER_ID", "CUST_ID", "CLIENT_ID", "PARTY_ID", "CUST_KEY"},
    {"ACCOUNT_ID", "ACCT_ID", "ACCT_NO", "ACCOUNT_NUMBER", "ACCT_KEY"},
    {"TRANSACTION_ID", "TXN_ID", "TRANS_ID", "TXN_NO"},
    {"AMOUNT", "AMT", "TXN_AMT", "TRANSACTION_AMOUNT", "VALUE"},
    {"DELETED_FLAG", "DEL_FLG", "IS_DELETED", "ACTIVE_FLAG", "IS_ACTIVE"},
]


def expand(token: str) -> str:
    return ABBREV.get(token.upper(), token.upper())


def synonyms_of(name: str) -> set[str]:
    n = name.upper()
    out: set[str] = {n}
    for group in SYNONYMS:
        if n in group:
            out |= group
    return out
