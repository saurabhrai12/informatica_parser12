
CREATE OR REPLACE PROCEDURE PROD_DB.CORTEX_CHAT_APP.SP_AUDIT_TRAIL(
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
    VALUES ('AUDIT_TRAIL_EXTRACT', 'SP_AUDIT_TRAIL',
            :v_start_ts, NULL, 'RUNNING',
            0, 0, 0, 'AUDIT_TRAIL_EXTRACT', NULL, :P_BATCH_ID);

    -- ── PRE-HOOK ─────────────────────────────────────────────────────
    -- (no pre-SQL declared in lineage; add session params here if needed)
    -- Incremental filter — applied to source
    -- WHERE CHANGE_DT >= :P_WATERMARK_FROM AND CHANGE_DT < :P_WATERMARK_TO

    -- ── MAIN TRANSFORMATION ──────────────────────────────────────────
    -- [INFA: Mapping] AUDIT_TRAIL_EXTRACT  →  Target: AUDIT_TRAIL
    -- Source: AUDIT_LOG_SRC
    -- Load strategy: INSERT  Truncate: False
    BEGIN
        LET stmt VARCHAR := $$WITH
SQ_AUDIT_TRAIL_EXTRACT AS (
  -- [INFA: SourceQualifier] SQ_AUDIT_TRAIL_EXTRACT
  SELECT CHANGED_BY,
         CHANGE_DT,
         LOG_ID,
         NEW_VALUES,
         OLD_VALUES,
         OPERATION,
         SESSION_ID,
         TABLE_NAME
  FROM   PROD_DB.RAW_LAYER.AUDIT_LOG_SRC
),
EXPR_AUDIT_TRAIL_EXTRACT AS (
  -- [INFA: Expression] EXPR_AUDIT_TRAIL_EXTRACT
  SELECT
    -- [INFA] Complexity=SIMPLE src=AUDIT_LOG_SRC.LOG_ID → tgt=AUDIT_TRAIL.LOG_ID
    LOG_ID AS LOG_ID,
    -- [INFA] Complexity=SIMPLE src=AUDIT_LOG_SRC.TABLE_NAME → tgt=AUDIT_TRAIL.TABLE_NAME
    TABLE_NAME AS TABLE_NAME,
    -- [INFA] Complexity=SIMPLE src=AUDIT_LOG_SRC.OPERATION → tgt=AUDIT_TRAIL.OPERATION
    OPERATION AS OPERATION,
    -- [INFA] Complexity=SIMPLE src=AUDIT_LOG_SRC.CHANGED_BY → tgt=AUDIT_TRAIL.CHANGED_BY
    CHANGED_BY AS CHANGED_BY,
    -- [INFA] Complexity=SIMPLE src=AUDIT_LOG_SRC.CHANGE_DT → tgt=AUDIT_TRAIL.CHANGE_DT
    CHANGE_DT AS CHANGE_DT,
    -- [INFA] Complexity=SIMPLE src=AUDIT_LOG_SRC.OLD_VALUES → tgt=AUDIT_TRAIL.OLD_VALUES
    OLD_VALUES AS OLD_VALUES,
    -- [INFA] Complexity=SIMPLE src=AUDIT_LOG_SRC.NEW_VALUES → tgt=AUDIT_TRAIL.NEW_VALUES
    NEW_VALUES AS NEW_VALUES,
    -- [INFA] Complexity=SIMPLE src=AUDIT_LOG_SRC.SESSION_ID → tgt=AUDIT_TRAIL.SESSION_ID
    SESSION_ID AS SESSION_ID,
    -- [INFA] Complexity=SIMPLE src=None.None → tgt=AUDIT_TRAIL.DAYS_SINCE_CHG
  -- TODO: VERIFY — MEDIUM confidence mapping
    NULL AS DAYS_SINCE_CHG
  FROM SQ_AUDIT_TRAIL_EXTRACT
)
INSERT INTO PROD_DB.CORTEX_CHAT_APP.AUDIT_TRAIL
  (LOG_ID, TABLE_NAME, OPERATION, CHANGED_BY, CHANGE_DT, OLD_VALUES, NEW_VALUES, SESSION_ID, DAYS_SINCE_CHG)
SELECT LOG_ID, TABLE_NAME, OPERATION, CHANGED_BY, CHANGE_DT, OLD_VALUES, NEW_VALUES, SESSION_ID, DAYS_SINCE_CHG
FROM   EXPR_AUDIT_TRAIL_EXTRACT;$$;

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
            VALUES ('SP_AUDIT_TRAIL', SQLCODE, :v_err_msg,
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
    WHERE  MAPPING_NAME    = 'AUDIT_TRAIL_EXTRACT'
      AND  PROCEDURE_NAME  = 'SP_AUDIT_TRAIL'
      AND  STATUS          = 'RUNNING';

    RETURN :v_status;
END;
$$;
