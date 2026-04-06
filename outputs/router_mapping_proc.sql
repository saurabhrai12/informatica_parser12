
CREATE OR REPLACE PROCEDURE PROD_DB.CORTEX_CHAT_APP.SP_HIGH_RISK_ALERTS(
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
    VALUES ('ALERT_ROUTER_LOAD', 'SP_HIGH_RISK_ALERTS',
            :v_start_ts, NULL, 'RUNNING',
            0, 0, 0, 'ALERT_ROUTER_LOAD', NULL, :P_BATCH_ID);

    -- ── PRE-HOOK ─────────────────────────────────────────────────────
    -- (no pre-SQL declared in lineage; add session params here if needed)

    -- ── MAIN TRANSFORMATION ──────────────────────────────────────────
    -- [INFA: Mapping] ALERT_ROUTER_LOAD  →  Target: HIGH_RISK_ALERTS
    -- Source: ALERTS_SRC
    -- Load strategy: INSERT  Truncate: False
    BEGIN
        LET stmt VARCHAR := $$WITH
SQ_ALERT_ROUTER_LOAD AS (
  -- [INFA: SourceQualifier] SQ_ALERT_ROUTER_LOAD
  SELECT ALERT_ID,
         ALERT_TYPE,
         CUST_ID,
         RISK_SCORE
  FROM   PROD_DB.RAW_LAYER.ALERTS_SRC
),
EXPR_ALERT_ROUTER_LOAD AS (
  -- [INFA: Expression] EXPR_ALERT_ROUTER_LOAD
  SELECT
    -- [INFA] Complexity=SIMPLE src=ALERTS_SRC.ALERT_ID → tgt=HIGH_RISK_ALERTS.ALERT_ID
    ALERT_ID AS ALERT_ID,
    -- [INFA] Complexity=SIMPLE src=ALERTS_SRC.ALERT_TYPE → tgt=HIGH_RISK_ALERTS.ALERT_TYPE
    ALERT_TYPE AS ALERT_TYPE,
    -- [INFA] Complexity=SIMPLE src=ALERTS_SRC.RISK_SCORE → tgt=HIGH_RISK_ALERTS.RISK_SCORE
    RISK_SCORE AS RISK_SCORE,
    -- [INFA] Complexity=SIMPLE src=ALERTS_SRC.CUST_ID → tgt=HIGH_RISK_ALERTS.CUST_ID
    CUST_ID AS CUST_ID
  FROM SQ_ALERT_ROUTER_LOAD
)
INSERT INTO PROD_DB.CORTEX_CHAT_APP.HIGH_RISK_ALERTS
  (ALERT_ID, ALERT_TYPE, RISK_SCORE, CUST_ID)
SELECT ALERT_ID, ALERT_TYPE, RISK_SCORE, CUST_ID
FROM   EXPR_ALERT_ROUTER_LOAD;$$;

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
            VALUES ('SP_HIGH_RISK_ALERTS', SQLCODE, :v_err_msg,
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
    WHERE  MAPPING_NAME    = 'ALERT_ROUTER_LOAD'
      AND  PROCEDURE_NAME  = 'SP_HIGH_RISK_ALERTS'
      AND  STATUS          = 'RUNNING';

    RETURN :v_status;
END;
$$;
