
CREATE OR REPLACE PROCEDURE PROD_DB.CORTEX_CHAT_APP.SP_ORDER_DETAIL_FACT(
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
    VALUES ('ORDER_DETAIL_JOIN', 'SP_ORDER_DETAIL_FACT',
            :v_start_ts, NULL, 'RUNNING',
            0, 0, 0, 'ORDER_DETAIL_JOIN', NULL, :P_BATCH_ID);

    -- ── PRE-HOOK ─────────────────────────────────────────────────────
    -- (no pre-SQL declared in lineage; add session params here if needed)

    -- ── MAIN TRANSFORMATION ──────────────────────────────────────────
    -- [INFA: Mapping] ORDER_DETAIL_JOIN  →  Target: ORDER_DETAIL_FACT
    -- Source: ORDER_ITEMS_SRC
    -- Load strategy: INSERT  Truncate: False
    BEGIN
        LET stmt VARCHAR := $$WITH
SQ_ORDER_DETAIL_JOIN AS (
  -- [INFA: SourceQualifier] SQ_ORDER_DETAIL_JOIN
  SELECT CUST_ID,
         ITEM_ID,
         ORDER_DT,
         ORDER_ID,
         PRODUCT_CD,
         QTY,
         STATUS_CD,
         UNIT_PRICE
  FROM   PROD_DB.RAW_LAYER.ORDER_ITEMS_SRC
),
EXPR_ORDER_DETAIL_JOIN AS (
  -- [INFA: Expression] EXPR_ORDER_DETAIL_JOIN
  SELECT
    -- [INFA] Complexity=SIMPLE src=ORDER_ITEMS_SRC.ITEM_ID → tgt=ORDER_DETAIL_FACT.ITEM_ID
    ITEM_ID AS ITEM_ID,
    -- [INFA] Complexity=SIMPLE src=ORDER_ITEMS_SRC.ORDER_ID → tgt=ORDER_DETAIL_FACT.ORDER_ID
    ORDER_ID AS ORDER_ID,
    -- [INFA] Complexity=SIMPLE src=ORDERS_SRC.CUST_ID → tgt=ORDER_DETAIL_FACT.CUST_ID
    CUST_ID AS CUST_ID,
    -- [INFA] Complexity=SIMPLE src=ORDER_ITEMS_SRC.PRODUCT_CD → tgt=ORDER_DETAIL_FACT.PRODUCT_CD
    PRODUCT_CD AS PRODUCT_CD,
    -- [INFA] Complexity=SIMPLE src=ORDER_ITEMS_SRC.QTY → tgt=ORDER_DETAIL_FACT.QTY
    QTY AS QTY,
    -- [INFA] Complexity=SIMPLE src=ORDER_ITEMS_SRC.UNIT_PRICE → tgt=ORDER_DETAIL_FACT.UNIT_PRICE
    UNIT_PRICE AS UNIT_PRICE,
    -- [INFA] Complexity=SIMPLE src=None.None → tgt=ORDER_DETAIL_FACT.LINE_AMT
  -- TODO: VERIFY — MEDIUM confidence mapping
    NULL AS LINE_AMT,
    -- [INFA] Complexity=SIMPLE src=ORDERS_SRC.ORDER_DT → tgt=ORDER_DETAIL_FACT.ORDER_DT
    ORDER_DT AS ORDER_DT,
    -- [INFA] Complexity=SIMPLE src=ORDERS_SRC.STATUS_CD → tgt=ORDER_DETAIL_FACT.STATUS_CD
    STATUS_CD AS STATUS_CD
  FROM SQ_ORDER_DETAIL_JOIN
)
INSERT INTO PROD_DB.CORTEX_CHAT_APP.ORDER_DETAIL_FACT
  (ITEM_ID, ORDER_ID, CUST_ID, PRODUCT_CD, QTY, UNIT_PRICE, LINE_AMT, ORDER_DT, STATUS_CD)
SELECT ITEM_ID, ORDER_ID, CUST_ID, PRODUCT_CD, QTY, UNIT_PRICE, LINE_AMT, ORDER_DT, STATUS_CD
FROM   EXPR_ORDER_DETAIL_JOIN;$$;

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
            VALUES ('SP_ORDER_DETAIL_FACT', SQLCODE, :v_err_msg,
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
    WHERE  MAPPING_NAME    = 'ORDER_DETAIL_JOIN'
      AND  PROCEDURE_NAME  = 'SP_ORDER_DETAIL_FACT'
      AND  STATUS          = 'RUNNING';

    RETURN :v_status;
END;
$$;
