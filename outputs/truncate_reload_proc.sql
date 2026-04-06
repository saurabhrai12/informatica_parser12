
CREATE OR REPLACE PROCEDURE PROD_DB.CORTEX_CHAT_APP.SP_PRODUCT_DIM(
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
    VALUES ('PRODUCT_DIM_RELOAD', 'SP_PRODUCT_DIM',
            :v_start_ts, NULL, 'RUNNING',
            0, 0, 0, 'PRODUCT_DIM_RELOAD', NULL, :P_BATCH_ID);

    -- ── PRE-HOOK ─────────────────────────────────────────────────────
    -- (no pre-SQL declared in lineage; add session params here if needed)

    -- ── MAIN TRANSFORMATION ──────────────────────────────────────────
    -- [INFA: Mapping] PRODUCT_DIM_RELOAD  →  Target: PRODUCT_DIM
    -- Source: PRODUCTS_SRC
    -- Load strategy: INSERT  Truncate: True
    BEGIN
        LET stmt VARCHAR := $$WITH
SQ_PRODUCTS AS (
  -- [INFA: SourceQualifier] SQ_PRODUCTS
  SELECT ACTIVE_FLG,
         CATEGORY_CD,
         EFF_DT,
         EXP_DT,
         PRODUCT_CD,
         PRODUCT_ID,
         PRODUCT_NAME,
         SUB_CAT_CD,
         UNIT_PRICE
  FROM   PROD_DB.RAW_LAYER.PRODUCTS_SRC
),
EXPR_PRODUCT AS (
  -- [INFA: Expression] EXPR_PRODUCT
  SELECT
    -- [INFA] Complexity=SIMPLE src=PRODUCTS_SRC.PRODUCT_ID → tgt=PRODUCT_DIM.PRODUCT_ID
    PRODUCT_ID AS PRODUCT_ID,
    -- [INFA] Complexity=SIMPLE src=PRODUCTS_SRC.PRODUCT_CD → tgt=PRODUCT_DIM.PRODUCT_CD
    PRODUCT_CD AS PRODUCT_CD,
    -- [INFA] Complexity=MODERATE src=PRODUCTS_SRC.PRODUCT_NAME → tgt=PRODUCT_DIM.PRODUCT_NAME
    -- Expression: UPPER(LTRIM(RTRIM(NVL(PRODUCT_NAME,'UNKNOWN'))))
    -- SF rewrite:  UPPER(LTRIM(RTRIM(COALESCE(PRODUCT_NAME,'UNKNOWN'))))
    UPPER(LTRIM(RTRIM(COALESCE(PRODUCT_NAME,'UNKNOWN')))) AS PRODUCT_NAME,
    -- [INFA] Complexity=MODERATE src=PRODUCTS_SRC.CATEGORY_CD → tgt=PRODUCT_DIM.CATEGORY_CD
    -- Expression: NVL(CATEGORY_CD,'MISC')
    -- SF rewrite:  COALESCE(CATEGORY_CD,'MISC')
    COALESCE(CATEGORY_CD,'MISC') AS CATEGORY_CD,
    -- [INFA] Complexity=MODERATE src=PRODUCTS_SRC.SUB_CAT_CD → tgt=PRODUCT_DIM.SUB_CAT_CD
    -- Expression: NVL(SUB_CAT_CD,'NA')
    -- SF rewrite:  COALESCE(SUB_CAT_CD,'NA')
    COALESCE(SUB_CAT_CD,'NA') AS SUB_CAT_CD,
    -- [INFA] Complexity=MODERATE src=PRODUCTS_SRC.UNIT_PRICE → tgt=PRODUCT_DIM.UNIT_PRICE
    -- Expression: NVL(UNIT_PRICE,0)
    -- SF rewrite:  COALESCE(UNIT_PRICE,0)
    COALESCE(UNIT_PRICE,0) AS UNIT_PRICE,
    -- [INFA] Complexity=MODERATE src=PRODUCTS_SRC.ACTIVE_FLG → tgt=PRODUCT_DIM.ACTIVE_FLG
    -- Expression: NVL(ACTIVE_FLG,'N')
    -- SF rewrite:  COALESCE(ACTIVE_FLG,'N')
    COALESCE(ACTIVE_FLG,'N') AS ACTIVE_FLG,
    -- [INFA] Complexity=MODERATE src=PRODUCTS_SRC.EFF_DT → tgt=PRODUCT_DIM.EFF_DT
    -- Expression: NVL(EFF_DT,TO_DATE('19000101','YYYYMMDD'))
    -- SF rewrite:  COALESCE(EFF_DT,TO_DATE('19000101','YYYYMMDD'))
    COALESCE(EFF_DT,TO_DATE('19000101','YYYYMMDD')) AS EFF_DT,
    -- [INFA] Complexity=MODERATE src=PRODUCTS_SRC.EXP_DT → tgt=PRODUCT_DIM.EXP_DT
    -- Expression: NVL(EXP_DT,TO_DATE('99991231','YYYYMMDD'))
    -- SF rewrite:  COALESCE(EXP_DT,TO_DATE('99991231','YYYYMMDD'))
    COALESCE(EXP_DT,TO_DATE('99991231','YYYYMMDD')) AS EXP_DT,
    -- [INFA] Complexity=SIMPLE src=None.None → tgt=PRODUCT_DIM.LOAD_TS
    -- Expression: SYSDATE
    -- SF rewrite:  CURRENT_TIMESTAMP()
  -- TODO: VERIFY — MEDIUM confidence mapping
    CURRENT_TIMESTAMP() AS LOAD_TS
  FROM SQ_PRODUCTS
)
-- [INFA: TruncateTarget] truncate before full reload
TRUNCATE TABLE PROD_DB.CORTEX_CHAT_APP.PRODUCT_DIM;
INSERT INTO PROD_DB.CORTEX_CHAT_APP.PRODUCT_DIM
  (PRODUCT_ID, PRODUCT_CD, PRODUCT_NAME, CATEGORY_CD, SUB_CAT_CD, UNIT_PRICE, ACTIVE_FLG, EFF_DT, EXP_DT, LOAD_TS)
SELECT PRODUCT_ID, PRODUCT_CD, PRODUCT_NAME, CATEGORY_CD, SUB_CAT_CD, UNIT_PRICE, ACTIVE_FLG, EFF_DT, EXP_DT, LOAD_TS
FROM   EXPR_PRODUCT;$$;

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
            VALUES ('SP_PRODUCT_DIM', SQLCODE, :v_err_msg,
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
    WHERE  MAPPING_NAME    = 'PRODUCT_DIM_RELOAD'
      AND  PROCEDURE_NAME  = 'SP_PRODUCT_DIM'
      AND  STATUS          = 'RUNNING';

    RETURN :v_status;
END;
$$;
