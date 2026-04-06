
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
    VALUES ('CUST_DIM_UPSERT', 'SP_CUSTOMER_DIM',
            :v_start_ts, NULL, 'RUNNING',
            0, 0, 0, 'CUST_DIM_UPSERT', NULL, :P_BATCH_ID);

    -- ── PRE-HOOK ─────────────────────────────────────────────────────
    -- (no pre-SQL declared in lineage; add session params here if needed)
    -- Incremental filter — applied to source
    -- WHERE LAST_MOD_DT >= :P_WATERMARK_FROM AND LAST_MOD_DT < :P_WATERMARK_TO

    -- ── MAIN TRANSFORMATION ──────────────────────────────────────────
    -- [INFA: Mapping] CUST_DIM_UPSERT  →  Target: CUSTOMER_DIM
    -- Source: CUSTOMER_DELTA_SRC
    -- Load strategy: INSERT  Truncate: False
    BEGIN
        LET stmt VARCHAR := $$WITH
SQ_CUST_DIM_UPSERT AS (
  -- [INFA: SourceQualifier] SQ_CUST_DIM_UPSERT
  SELECT CREATED_DT,
         CUST_ID,
         CUST_NAME,
         EMAIL,
         KYC_STATUS,
         LAST_MOD_DT,
         PHONE,
         SEGMENT_CD
  FROM   PROD_DB.RAW_LAYER.CUSTOMER_DELTA_SRC
),
EXPR_CUST_DIM_UPSERT AS (
  -- [INFA: Expression] EXPR_CUST_DIM_UPSERT
  SELECT
    -- [INFA] Complexity=SIMPLE src=CUSTOMER_DELTA_SRC.CUST_ID → tgt=CUSTOMER_DIM.CUST_ID
    CUST_ID AS CUST_ID,
    -- [INFA] Complexity=SIMPLE src=CUSTOMER_DELTA_SRC.CUST_NAME → tgt=CUSTOMER_DIM.CUST_NAME
    CUST_NAME AS CUST_NAME,
    -- [INFA] Complexity=SIMPLE src=CUSTOMER_DELTA_SRC.EMAIL → tgt=CUSTOMER_DIM.EMAIL
    EMAIL AS EMAIL,
    -- [INFA] Complexity=SIMPLE src=CUSTOMER_DELTA_SRC.PHONE → tgt=CUSTOMER_DIM.PHONE
    PHONE AS PHONE,
    -- [INFA] Complexity=SIMPLE src=CUSTOMER_DELTA_SRC.SEGMENT_CD → tgt=CUSTOMER_DIM.SEGMENT_CD
    SEGMENT_CD AS SEGMENT_CD,
    -- [INFA] Complexity=SIMPLE src=CUSTOMER_DELTA_SRC.KYC_STATUS → tgt=CUSTOMER_DIM.KYC_STATUS
    KYC_STATUS AS KYC_STATUS,
    -- [INFA] Complexity=SIMPLE src=CUSTOMER_DELTA_SRC.LAST_MOD_DT → tgt=CUSTOMER_DIM.LAST_MOD_DT
    LAST_MOD_DT AS LAST_MOD_DT,
    -- [INFA] Complexity=SIMPLE src=CUSTOMER_DELTA_SRC.CREATED_DT → tgt=CUSTOMER_DIM.CREATED_DT
    CREATED_DT AS CREATED_DT,
    -- [INFA] Complexity=SIMPLE src=None.None → tgt=CUSTOMER_DIM.LOAD_TS
  -- TODO: VERIFY — MEDIUM confidence mapping
    NULL AS LOAD_TS,
    -- [INFA] Complexity=SIMPLE src=None.None → tgt=CUSTOMER_DIM.BATCH_ID
  -- TODO: VERIFY — MEDIUM confidence mapping
    NULL AS BATCH_ID
  FROM SQ_CUST_DIM_UPSERT
)
INSERT INTO PROD_DB.CORTEX_CHAT_APP.CUSTOMER_DIM
  (CUST_ID, CUST_NAME, EMAIL, PHONE, SEGMENT_CD, KYC_STATUS, LAST_MOD_DT, CREATED_DT, LOAD_TS, BATCH_ID)
SELECT CUST_ID, CUST_NAME, EMAIL, PHONE, SEGMENT_CD, KYC_STATUS, LAST_MOD_DT, CREATED_DT, LOAD_TS, BATCH_ID
FROM   EXPR_CUST_DIM_UPSERT;$$;

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
    WHERE  MAPPING_NAME    = 'CUST_DIM_UPSERT'
      AND  PROCEDURE_NAME  = 'SP_CUSTOMER_DIM'
      AND  STATUS          = 'RUNNING';

    RETURN :v_status;
END;
$$;
