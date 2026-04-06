
CREATE OR REPLACE PROCEDURE PROD_DB.CORTEX_CHAT_APP.SP_TXN_FACT(
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
    VALUES ('TXN_FACT_LOAD', 'SP_TXN_FACT',
            :v_start_ts, NULL, 'RUNNING',
            0, 0, 0, 'TXN_FACT_LOAD', NULL, :P_BATCH_ID);

    -- ── PRE-HOOK ─────────────────────────────────────────────────────
    -- (no pre-SQL declared in lineage; add session params here if needed)

    -- ── MAIN TRANSFORMATION ──────────────────────────────────────────
    -- [INFA: Mapping] TXN_FACT_LOAD  →  Target: TXN_FACT
    -- Source: TRANSACTIONS_SRC
    -- Load strategy: INSERT  Truncate: False
    BEGIN
        LET stmt VARCHAR := $$WITH
SQ_TXN AS (
  -- [INFA: SourceQualifier] SQ_TXN — SQ override SQL
  SELECT * FROM TRANSACTIONS_SRC WHERE TXN_DT >= CURRENT_TIMESTAMP() - 30
),
EXPR_TXN AS (
  -- [INFA: Expression] EXPR_TXN
  SELECT
    -- [INFA] Complexity=SIMPLE src=TRANSACTIONS_SRC.TXN_ID → tgt=TXN_FACT.TXN_ID
    TXN_ID AS TXN_ID,
    -- [INFA] Complexity=SIMPLE src=TRANSACTIONS_SRC.CUST_ID → tgt=TXN_FACT.CUST_ID
    CUST_ID AS CUST_ID,
    -- [INFA] Complexity=MODERATE src=TRANSACTIONS_SRC.TXN_AMT → tgt=TXN_FACT.TXN_AMOUNT
    -- Expression: NVL(TXN_AMT, 0)
    -- SF rewrite:  COALESCE(TXN_AMT, 0)
    COALESCE(TXN_AMT, 0) AS TXN_AMOUNT,
    -- [INFA] Complexity=MODERATE src=TRANSACTIONS_SRC.TXN_DT → tgt=TXN_FACT.TXN_DATE
    -- Expression: TO_DATE(TO_CHAR(TXN_DT,'YYYY-MM-DD'),'YYYY-MM-DD')
    -- SF rewrite:  TO_DATE(TO_VARCHAR(TXN_DT,'YYYY-MM-DD'),'YYYY-MM-DD')
    TO_DATE(TO_VARCHAR(TXN_DT,'YYYY-MM-DD'),'YYYY-MM-DD') AS TXN_DATE,
    -- [INFA] Complexity=MODERATE src=TRANSACTIONS_SRC.TXN_STATUS → tgt=TXN_FACT.TXN_STATUS_DESC
    -- Expression: DECODE(TXN_STATUS,'APPR','APPROVED','DECL','DECLINED','PEND','PENDING','UNKNOWN')
    -- SF rewrite:  CASE TXN_STATUS
        WHEN 'APPR' THEN 'APPROVED'
        WHEN 'DECL' THEN 'DECLINED'
        WHEN 'PEND' THEN 'PENDING'
        ELSE 'UNKNOWN'
    END
    CASE TXN_STATUS
        WHEN 'APPR' THEN 'APPROVED'
        WHEN 'DECL' THEN 'DECLINED'
        WHEN 'PEND' THEN 'PENDING'
        ELSE 'UNKNOWN'
    END AS TXN_STATUS_DESC,
    -- [INFA] Complexity=MODERATE src=TRANSACTIONS_SRC.CHANNEL_CD → tgt=TXN_FACT.CHANNEL_NAME
    -- Expression: IIF(CHANNEL_CD='WEB','ONLINE',IIF(CHANNEL_CD='MOB','MOBILE','BRANCH'))
    -- SF rewrite:  CASE WHEN CHANNEL_CD='WEB' THEN 'ONLINE' ELSE CASE WHEN (CHANNEL_CD='MOB','MOBILE','BRANCH' END)
    CASE WHEN CHANNEL_CD='WEB' THEN 'ONLINE' ELSE CASE WHEN (CHANNEL_CD='MOB','MOBILE','BRANCH' END) AS CHANNEL_NAME,
    -- [INFA] Complexity=SIMPLE src=TRANSACTIONS_SRC.CREATED_DT → tgt=TXN_FACT.LOAD_TS
    -- Expression: SYSDATE
    -- SF rewrite:  CURRENT_TIMESTAMP()
    CURRENT_TIMESTAMP() AS LOAD_TS,
    -- [INFA] Complexity=MODERATE src=TRANSACTIONS_SRC.TXN_AMT → tgt=TXN_FACT.IS_HIGH_VALUE
    -- Expression: IIF(NVL(TXN_AMT,0) > 10000,'Y','N')
    -- SF rewrite:  CASE WHEN COALESCE(TXN_AMT THEN 0) > 10000 ELSE 'Y','N' END
    CASE WHEN COALESCE(TXN_AMT THEN 0) > 10000 ELSE 'Y','N' END AS IS_HIGH_VALUE
  FROM SQ_TXN
)
INSERT INTO PROD_DB.CORTEX_CHAT_APP.TXN_FACT
  (TXN_ID, CUST_ID, TXN_AMOUNT, TXN_DATE, TXN_STATUS_DESC, CHANNEL_NAME, LOAD_TS, IS_HIGH_VALUE)
SELECT TXN_ID, CUST_ID, TXN_AMOUNT, TXN_DATE, TXN_STATUS_DESC, CHANNEL_NAME, LOAD_TS, IS_HIGH_VALUE
FROM   EXPR_TXN;$$;

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
            VALUES ('SP_TXN_FACT', SQLCODE, :v_err_msg,
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
    WHERE  MAPPING_NAME    = 'TXN_FACT_LOAD'
      AND  PROCEDURE_NAME  = 'SP_TXN_FACT'
      AND  STATUS          = 'RUNNING';

    RETURN :v_status;
END;
$$;
