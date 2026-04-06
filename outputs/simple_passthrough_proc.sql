
CREATE OR REPLACE PROCEDURE PROD_DB.CORTEX_CHAT_APP.SP_CUSTOMER_DIM(
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
    VALUES ('CUST_DIM_LOAD', 'SP_CUSTOMER_DIM',
            :v_start_ts, NULL, 'RUNNING',
            0, 0, 0, 'CUST_DIM_LOAD', NULL, :P_BATCH_ID);

    -- ── PRE-HOOK ─────────────────────────────────────────────────────
    -- (no pre-SQL declared in lineage; add session params here if needed)

    -- ── MAIN TRANSFORMATION ──────────────────────────────────────────
    -- [INFA: Mapping] CUST_DIM_LOAD  →  Target: CUSTOMER_DIM
    -- Source: CUSTOMER_SRC
    -- Load strategy: INSERT  Truncate: False
    BEGIN
        LET stmt VARCHAR := $$WITH
SQ_CUST_DIM_LOAD AS (
  -- [INFA: SourceQualifier] SQ_CUST_DIM_LOAD
  SELECT CUSTOMER_ID,
         CUSTOMER_NAME
  FROM   PROD_DB.RAW_LAYER.CUSTOMER_SRC
),
EXPR_CUST_DIM_LOAD AS (
  -- [INFA: Expression] EXPR_CUST_DIM_LOAD
  SELECT
    -- [INFA] Complexity=SIMPLE src=CUSTOMER_SRC.CUSTOMER_ID → tgt=CUSTOMER_DIM.CUSTOMER_ID
    CUSTOMER_ID AS CUSTOMER_ID,
    -- [INFA] Complexity=SIMPLE src=CUSTOMER_SRC.CUSTOMER_NAME → tgt=CUSTOMER_DIM.CUSTOMER_NAME
    CUSTOMER_NAME AS CUSTOMER_NAME
  FROM SQ_CUST_DIM_LOAD
)
INSERT INTO PROD_DB.CORTEX_CHAT_APP.CUSTOMER_DIM
  (CUSTOMER_ID, CUSTOMER_NAME)
SELECT CUSTOMER_ID, CUSTOMER_NAME
FROM   EXPR_CUST_DIM_LOAD;$$;

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
            VALUES ('SP_CUSTOMER_DIM', SQLCODE, :v_err_msg,
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
    WHERE  MAPPING_NAME    = 'CUST_DIM_LOAD'
      AND  PROCEDURE_NAME  = 'SP_CUSTOMER_DIM'
      AND  STATUS          = 'RUNNING';

    RETURN :v_status;
END;
$$;
