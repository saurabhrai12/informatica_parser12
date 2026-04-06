
CREATE OR REPLACE PROCEDURE PROD_DB.CORTEX_CHAT_APP.SP_DAILY_TXN_SUMMARY(
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
    VALUES ('DAILY_TXN_AGG', 'SP_DAILY_TXN_SUMMARY',
            :v_start_ts, NULL, 'RUNNING',
            0, 0, 0, 'DAILY_TXN_AGG', NULL, :P_BATCH_ID);

    -- ── PRE-HOOK ─────────────────────────────────────────────────────
    -- (no pre-SQL declared in lineage; add session params here if needed)

    -- ── MAIN TRANSFORMATION ──────────────────────────────────────────
    -- [INFA: Mapping] DAILY_TXN_AGG  →  Target: DAILY_TXN_SUMMARY
    -- Source: TRANSACTIONS_SRC
    -- Load strategy: INSERT  Truncate: False
    BEGIN
        LET stmt VARCHAR := $$WITH
SQ_DAILY_TXN_AGG AS (
  -- [INFA: SourceQualifier] SQ_DAILY_TXN_AGG
  SELECT CHANNEL_CD,
         CUST_ID,
         TXN_DT
  FROM   PROD_DB.RAW_LAYER.TRANSACTIONS_SRC
),
EXPR_DAILY_TXN_AGG AS (
  -- [INFA: Expression] EXPR_DAILY_TXN_AGG
  SELECT
    -- [INFA] Complexity=SIMPLE src=TRANSACTIONS_SRC.CUST_ID → tgt=DAILY_TXN_SUMMARY.CUST_ID
    CUST_ID AS CUST_ID,
    -- [INFA] Complexity=SIMPLE src=TRANSACTIONS_SRC.TXN_DT → tgt=DAILY_TXN_SUMMARY.TXN_DT
    TXN_DT AS TXN_DT,
    -- [INFA] Complexity=SIMPLE src=TRANSACTIONS_SRC.CHANNEL_CD → tgt=DAILY_TXN_SUMMARY.CHANNEL_CD
    CHANNEL_CD AS CHANNEL_CD,
    -- [INFA] Complexity=SIMPLE src=None.None → tgt=DAILY_TXN_SUMMARY.TXN_COUNT
  -- TODO: VERIFY — MEDIUM confidence mapping
    NULL AS TXN_COUNT,
    -- [INFA] Complexity=SIMPLE src=None.None → tgt=DAILY_TXN_SUMMARY.TOTAL_AMT
  -- TODO: VERIFY — MEDIUM confidence mapping
    NULL AS TOTAL_AMT,
    -- [INFA] Complexity=SIMPLE src=None.None → tgt=DAILY_TXN_SUMMARY.AVG_AMT
  -- TODO: VERIFY — MEDIUM confidence mapping
    NULL AS AVG_AMT,
    -- [INFA] Complexity=SIMPLE src=None.None → tgt=DAILY_TXN_SUMMARY.MAX_AMT
  -- TODO: VERIFY — MEDIUM confidence mapping
    NULL AS MAX_AMT,
    -- [INFA] Complexity=SIMPLE src=None.None → tgt=DAILY_TXN_SUMMARY.RISK_TXN_COUNT
  -- TODO: VERIFY — MEDIUM confidence mapping
    NULL AS RISK_TXN_COUNT
  FROM SQ_DAILY_TXN_AGG
)
INSERT INTO PROD_DB.CORTEX_CHAT_APP.DAILY_TXN_SUMMARY
  (CUST_ID, TXN_DT, CHANNEL_CD, TXN_COUNT, TOTAL_AMT, AVG_AMT, MAX_AMT, RISK_TXN_COUNT)
SELECT CUST_ID, TXN_DT, CHANNEL_CD, TXN_COUNT, TOTAL_AMT, AVG_AMT, MAX_AMT, RISK_TXN_COUNT
FROM   EXPR_DAILY_TXN_AGG;$$;

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
            VALUES ('SP_DAILY_TXN_SUMMARY', SQLCODE, :v_err_msg,
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
    WHERE  MAPPING_NAME    = 'DAILY_TXN_AGG'
      AND  PROCEDURE_NAME  = 'SP_DAILY_TXN_SUMMARY'
      AND  STATUS          = 'RUNNING';

    RETURN :v_status;
END;
$$;
