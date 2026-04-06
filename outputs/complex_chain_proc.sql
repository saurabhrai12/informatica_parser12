
CREATE OR REPLACE PROCEDURE PROD_DB.CORTEX_CHAT_APP.SP_FRAUD_ALERTS_FCT(
    P_WATERMARK_FROM TIMESTAMP_NTZ DEFAULT NULL,
    P_WATERMARK_TO   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    P_BATCH_ID       VARCHAR       DEFAULT NULL,
    P_BATCH_SIZE     INTEGER       DEFAULT NULL,
    P_DRY_RUN        BOOLEAN       DEFAULT FALSE
)
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
DECLARE
    v_status        VARCHAR        DEFAULT 'RUNNING';
    v_rows_inserted INTEGER        DEFAULT 0;
    v_rows_updated  INTEGER        DEFAULT 0;
    v_err_msg       VARCHAR;
    v_failed_sql    VARCHAR;
    v_start_ts      TIMESTAMP_NTZ  DEFAULT CURRENT_TIMESTAMP();
BEGIN
    -- ── AUDIT: start ─────────────────────────────────────────────────
    INSERT INTO PROD_DB.CORTEX_CHAT_APP.MIGRATION_AUDIT_LOG
        (MAPPING_NAME, PROCEDURE_NAME, EXEC_START_TS, EXEC_END_TS, STATUS,
         ROWS_INSERTED, ROWS_UPDATED, ROWS_DELETED, INFORMATICA_MAPPING_REF, ERROR_MESSAGE, BATCH_ID)
    VALUES ('FRAUD_ALERT_PIPELINE', 'SP_FRAUD_ALERTS_FCT',
            :v_start_ts, NULL, 'RUNNING',
            0, 0, 0, 'FRAUD_ALERT_PIPELINE', NULL, :P_BATCH_ID);

    -- ── PRE-HOOK ─────────────────────────────────────────────────────
    -- (no pre-SQL declared in lineage; add session params here if needed)

    -- ── MAIN TRANSFORMATION ──────────────────────────────────────────
    -- [INFA: Mapping] FRAUD_ALERT_PIPELINE  →  Target: FRAUD_ALERTS_FCT
    -- Source: UNKNOWN_SOURCE
    -- Load strategy: INSERT  Truncate: False
    BEGIN
        LET stmt VARCHAR := $$WITH
SQ_FRAUD_ALERT_PIPELINE AS (
  -- [INFA: SourceQualifier] SQ_FRAUD_ALERT_PIPELINE
  SELECT ACCT_ID,
         CUST_ID,
         TXN_AMT,
         TXN_DT,
         TXN_ID
  FROM   PROD_DB.RAW_LAYER.UNKNOWN_SOURCE
),
EXPR_FRAUD_ALERT_PIPELINE AS (
  -- [INFA: Expression] EXPR_FRAUD_ALERT_PIPELINE
  SELECT
    -- [INFA] Complexity=SIMPLE src=None.None → tgt=FRAUD_ALERTS_FCT.ALERT_SK
  -- TODO: VERIFY — MEDIUM confidence mapping
    NULL AS ALERT_SK,
    -- [INFA] Complexity=SIMPLE src=TXN_RAW_SRC.TXN_ID → tgt=FRAUD_ALERTS_FCT.TXN_ID
    TXN_ID AS TXN_ID,
    -- [INFA] Complexity=SIMPLE src=TXN_RAW_SRC.ACCT_ID → tgt=FRAUD_ALERTS_FCT.ACCT_ID
    ACCT_ID AS ACCT_ID,
    -- [INFA] Complexity=SIMPLE src=TXN_RAW_SRC.CUST_ID → tgt=FRAUD_ALERTS_FCT.CUST_ID
    CUST_ID AS CUST_ID,
    -- [INFA] Complexity=SIMPLE src=TXN_RAW_SRC.TXN_AMT → tgt=FRAUD_ALERTS_FCT.TXN_AMT
    TXN_AMT AS TXN_AMT,
    -- [INFA] Complexity=SIMPLE src=TXN_RAW_SRC.TXN_DT → tgt=FRAUD_ALERTS_FCT.TXN_DT
    TXN_DT AS TXN_DT,
    -- [INFA] Complexity=SIMPLE src=None.None → tgt=FRAUD_ALERTS_FCT.TXN_AMT_BAND
  -- TODO: VERIFY — MEDIUM confidence mapping
    NULL AS TXN_AMT_BAND,
    -- [INFA] Complexity=SIMPLE src=None.None → tgt=FRAUD_ALERTS_FCT.FRAUD_SCORE
  -- TODO: VERIFY — MEDIUM confidence mapping
    NULL AS FRAUD_SCORE,
    -- [INFA] Complexity=SIMPLE src=None.None → tgt=FRAUD_ALERTS_FCT.FRAUD_REASON
  -- TODO: VERIFY — MEDIUM confidence mapping
    NULL AS FRAUD_REASON,
    -- [INFA] Complexity=SIMPLE src=None.None → tgt=FRAUD_ALERTS_FCT.CUST_SEGMENT
  -- TODO: VERIFY — MEDIUM confidence mapping
    NULL AS CUST_SEGMENT,
    -- [INFA] Complexity=SIMPLE src=None.None → tgt=FRAUD_ALERTS_FCT.ACCT_RISK_TIER
  -- TODO: VERIFY — MEDIUM confidence mapping
    NULL AS ACCT_RISK_TIER,
    -- [INFA] Complexity=SIMPLE src=None.None → tgt=FRAUD_ALERTS_FCT.LOAD_TS
  -- TODO: VERIFY — MEDIUM confidence mapping
    NULL AS LOAD_TS
  FROM SQ_FRAUD_ALERT_PIPELINE
)
INSERT INTO PROD_DB.CORTEX_CHAT_APP.FRAUD_ALERTS_FCT
  (ALERT_SK, TXN_ID, ACCT_ID, CUST_ID, TXN_AMT, TXN_DT, TXN_AMT_BAND, FRAUD_SCORE, FRAUD_REASON, CUST_SEGMENT, ACCT_RISK_TIER, LOAD_TS)
SELECT ALERT_SK, TXN_ID, ACCT_ID, CUST_ID, TXN_AMT, TXN_DT, TXN_AMT_BAND, FRAUD_SCORE, FRAUD_REASON, CUST_SEGMENT, ACCT_RISK_TIER, LOAD_TS
FROM   EXPR_FRAUD_ALERT_PIPELINE;$$;

        IF (NOT P_DRY_RUN) THEN
            EXECUTE IMMEDIATE :stmt;
            v_rows_inserted := SQLROWCOUNT;
        ELSE
            -- DRY RUN mode: return preview query, do not write
            RETURN 'DRY_RUN: ' || :stmt;
        END IF;

        v_status := 'SUCCESS';
    EXCEPTION
        WHEN OTHER THEN
            v_status     := 'FAILED';
            v_err_msg    := SQLERRM;
            v_failed_sql := stmt;
            INSERT INTO PROD_DB.CORTEX_CHAT_APP.MIGRATION_ERROR_LOG
                (PROC_NAME, ERROR_CODE, ERROR_MESSAGE, FAILED_SQL, EXEC_TS, BATCH_ID)
            VALUES ('SP_FRAUD_ALERTS_FCT', SQLCODE, :v_err_msg,
                    :v_failed_sql, CURRENT_TIMESTAMP(), :P_BATCH_ID);
    END;

    -- ── ROW COUNT VALIDATION ─────────────────────────────────────────
    -- Check inserted vs expected; raise if delta > 5%
    -- (Adjust threshold per data volume SLA)

    -- ── AUDIT: end ────────────────────────────────────────────────────
    UPDATE PROD_DB.CORTEX_CHAT_APP.MIGRATION_AUDIT_LOG
    SET    EXEC_END_TS   = CURRENT_TIMESTAMP(),
           STATUS        = :v_status,
           ROWS_INSERTED = :v_rows_inserted,
           ROWS_UPDATED  = :v_rows_updated,
           ERROR_MESSAGE = :v_err_msg
    WHERE  MAPPING_NAME    = 'FRAUD_ALERT_PIPELINE'
      AND  PROCEDURE_NAME  = 'SP_FRAUD_ALERTS_FCT'
      AND  STATUS          = 'RUNNING';

    RETURN :v_status;
END;
$$;
