
CREATE OR REPLACE PROCEDURE PROD_DB.CORTEX_CHAT_APP.SP_ORDERS_ENRICHED(
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
    VALUES ('CUST_ENRICH_LOAD', 'SP_ORDERS_ENRICHED',
            :v_start_ts, NULL, 'RUNNING',
            0, 0, 0, 'CUST_ENRICH_LOAD', NULL, :P_BATCH_ID);

    -- ── PRE-HOOK ─────────────────────────────────────────────────────
    -- (no pre-SQL declared in lineage; add session params here if needed)

    -- ── MAIN TRANSFORMATION ──────────────────────────────────────────
    -- [INFA: Mapping] CUST_ENRICH_LOAD  →  Target: ORDERS_ENRICHED
    -- Source: ORDERS_SRC
    -- Load strategy: INSERT  Truncate: False
    BEGIN
        LET stmt VARCHAR := $$WITH
SQ_CUST_ENRICH_LOAD AS (
  -- [INFA: SourceQualifier] SQ_CUST_ENRICH_LOAD
  SELECT CUST_ID,
         ORDER_AMT,
         ORDER_DT,
         ORDER_ID,
         PRODUCT_CD
  FROM   PROD_DB.RAW_LAYER.ORDERS_SRC
),
EXPR_CUST_ENRICH_LOAD AS (
  -- [INFA: Expression] EXPR_CUST_ENRICH_LOAD
  SELECT
    -- [INFA] Complexity=SIMPLE src=ORDERS_SRC.ORDER_ID → tgt=ORDERS_ENRICHED.ORDER_ID
    ORDER_ID AS ORDER_ID,
    -- [INFA] Complexity=SIMPLE src=ORDERS_SRC.CUST_ID → tgt=ORDERS_ENRICHED.CUST_ID
    CUST_ID AS CUST_ID,
    -- [INFA] Complexity=SIMPLE src=ORDERS_SRC.PRODUCT_CD → tgt=ORDERS_ENRICHED.PRODUCT_CD
    PRODUCT_CD AS PRODUCT_CD,
    -- [INFA] Complexity=SIMPLE src=ORDERS_SRC.ORDER_AMT → tgt=ORDERS_ENRICHED.ORDER_AMT
    ORDER_AMT AS ORDER_AMT,
    -- [INFA] Complexity=SIMPLE src=ORDERS_SRC.ORDER_DT → tgt=ORDERS_ENRICHED.ORDER_DT
    ORDER_DT AS ORDER_DT,
    -- [INFA] Complexity=SIMPLE src=None.None → tgt=ORDERS_ENRICHED.CUST_SEGMENT
  -- TODO: VERIFY — MEDIUM confidence mapping
    NULL AS CUST_SEGMENT,
    -- [INFA] Complexity=SIMPLE src=None.None → tgt=ORDERS_ENRICHED.CUST_TIER
  -- TODO: VERIFY — MEDIUM confidence mapping
    NULL AS CUST_TIER
  FROM SQ_CUST_ENRICH_LOAD
)
INSERT INTO PROD_DB.CORTEX_CHAT_APP.ORDERS_ENRICHED
  (ORDER_ID, CUST_ID, PRODUCT_CD, ORDER_AMT, ORDER_DT, CUST_SEGMENT, CUST_TIER)
SELECT ORDER_ID, CUST_ID, PRODUCT_CD, ORDER_AMT, ORDER_DT, CUST_SEGMENT, CUST_TIER
FROM   EXPR_CUST_ENRICH_LOAD;$$;

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
            VALUES ('SP_ORDERS_ENRICHED', SQLCODE, :v_err_msg,
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
    WHERE  MAPPING_NAME    = 'CUST_ENRICH_LOAD'
      AND  PROCEDURE_NAME  = 'SP_ORDERS_ENRICHED'
      AND  STATUS          = 'RUNNING';

    RETURN :v_status;
END;
$$;
