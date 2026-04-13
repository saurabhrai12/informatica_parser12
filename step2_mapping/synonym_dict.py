"""Domain abbreviation + synonym dictionary for Step 2 column matching.

Agent-modifiable: extend, never remove. See CLAUDE.md and
mapping_identification.txt §"SEMANTIC MATCHING RULES".
"""

ABBREV: dict[str, str] = {
    # General shorthand
    "AMT": "AMOUNT", "QTY": "QUANTITY", "DT": "DATE", "CD": "CODE",
    "DESC": "DESCRIPTION", "NBR": "NUMBER", "NO": "NUMBER", "TYP": "TYPE",
    "IND": "INDICATOR", "ADDR": "ADDRESS", "CUST": "CUSTOMER",
    "ACCT": "ACCOUNT", "TXN": "TRANSACTION", "BAL": "BALANCE",
    "EFF": "EFFECTIVE", "EXP": "EXPIRY", "SRC": "SOURCE", "TGT": "TARGET",
    "STR": "START", "CRT": "CREATED", "UPD": "UPDATED", "DEL": "DELETED",
    "FLG": "FLAG", "SEQ": "SEQUENCE", "REF": "REFERENCE", "CAT": "CATEGORY",
    "ID": "IDENTIFIER", "PK": "PRIMARY_KEY", "FK": "FOREIGN_KEY",
    "DIM": "DIMENSION", "FCT": "FACT", "STG": "STAGING", "AGG": "AGGREGATE",
    # Geographic
    "CNTRY": "COUNTRY", "CTRY": "COUNTRY", "CNTR": "COUNTRY",
    "ADDR1": "ADDRESS_LINE1", "ADDR2": "ADDRESS_LINE2",
    "ZIP": "POSTAL_CODE", "POST": "POSTAL",
    # AML / financial crime domain
    "ALERT": "ALERT", "RISK": "RISK_SCORE", "SAR": "SAR_FLAG",
    "STRCT": "STRUCTURING", "FRAUD": "FRAUD_INDICATOR",
    "KYC": "KNOW_YOUR_CUSTOMER", "AML": "ANTI_MONEY_LAUNDERING",
    "MERCHANT": "MERCHANT", "CHANNEL": "CHANNEL", "BAND": "BAND",
    "ANALYST": "ANALYST", "RESOLVED": "RESOLVED",
    # Temporal extras
    "TS": "TIMESTAMP", "TMSTMP": "TIMESTAMP", "LOAD": "LOAD",
    "INS": "INSERT", "MOD": "MODIFIED", "LAST": "LAST",
    # Status / flag extras
    "STAT": "STATUS", "ACTV": "ACTIVE", "INACTV": "INACTIVE",
    "PEND": "PENDING", "ESCL": "ESCALATED",
    # Numeric / financial
    "BAL": "BALANCE", "LMT": "LIMIT", "CRDT": "CREDIT", "DBT": "DEBIT",
    "PCT": "PERCENT", "SCORE": "SCORE", "RATE": "RATE",
    # Common Oracle prefix single-letters (strip in normaliser)
    "C": "C", "N": "N", "D": "D",
}

SYNONYMS: list[set[str]] = [
    # Temporal lifecycle
    {"CREATED_DATE", "CREATION_DATE", "CREATE_DT", "INSERT_DATE", "LOAD_DATE", "INS_DT", "CRT_DT"},
    {"MODIFIED_DATE", "UPDATE_DATE", "LAST_UPDATED", "LAST_MODIFIED_DT", "UPD_DT", "LAST_UPD_DT"},
    {"RESOLVED_DATE", "RESOLVED_DT", "RESOLUTION_DATE", "CLOSE_DATE", "CLOSED_DT"},
    {"EFFECTIVE_DATE", "EFF_DT", "START_DATE", "VALID_FROM", "EFF_FROM"},
    {"EXPIRY_DATE", "EXP_DT", "END_DATE", "VALID_TO", "EFF_TO"},
    # Status / state
    {"STATUS", "STATE", "STATUS_CD", "RECORD_STATUS", "STAT",
     "TXN_STATUS", "ALERT_STATUS", "RECORD_STATE"},
    # Entity identifiers
    {"CUSTOMER_ID", "CUST_ID", "CLIENT_ID", "PARTY_ID", "CUST_KEY", "CUSTOMER_KEY"},
    {"ACCOUNT_ID", "ACCT_ID", "ACCT_NO", "ACCOUNT_NUMBER", "ACCT_KEY"},
    {"TRANSACTION_ID", "TXN_ID", "TRANS_ID", "TXN_NO"},
    {"ALERT_ID", "ALERT_KEY", "ALERT_NO"},
    # Financial
    {"AMOUNT", "AMT", "TXN_AMT", "TRANSACTION_AMOUNT", "VALUE", "TRANSACTION_VALUE"},
    # Flags / booleans
    {"DELETED_FLAG", "DEL_FLG", "IS_DELETED", "ACTIVE_FLAG", "IS_ACTIVE", "ACTIVE_FLG"},
    {"SAR_FLAG", "SAR_FLG", "SAR_FILED", "IS_SAR", "SAR_INDICATOR"},
    # Geographic
    {"COUNTRY_CODE", "CNTRY_CD", "COUNTRY_CD", "CTRY_CD", "ISO_COUNTRY"},
    # Enum / code columns
    {"ALERT_TYPE", "ALERT_TYP", "ALERT_TYPE_CODE", "ALERT_CATEGORY"},
    {"CHANNEL_CODE", "CHANNEL_CD", "CHANNEL", "TXN_CHANNEL"},
    # Risk / scoring
    {"RISK_SCORE", "RISK_BAND", "RISK_TIER", "RISK_LEVEL", "RISK_RATING", "RISK_CATEGORY"},
    # Analyst / user references
    {"ANALYST_ID", "ANALYST_USER_ID", "ASSIGNED_TO", "OWNER_ID", "ASSIGNED_ANALYST"},
    # Name columns
    {"CUSTOMER_NAME", "CUST_NAME", "CLIENT_NAME", "FULL_NAME", "NAME"},
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
