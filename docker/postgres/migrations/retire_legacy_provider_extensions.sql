-- SPDX-License-Identifier: Apache-2.0
-- Existing-volume preflight for retiring the legacy provider-network extensions.
-- Run 03_cron_batch_retrieval.sql first. This migration refuses extension
-- removal while the retired job, any independent cron job, any retired helper,
-- an unexpected table-like extension member, or an explicit DEPENDS ON EXTENSION
-- dependency still exists. DROP EXTENSION ... RESTRICT remains the final
-- PostgreSQL-owned dependency boundary after these stricter preservation checks.

BEGIN;
SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
    legacy_job_count BIGINT := 0;
    remaining_job_count BIGINT := 0;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_extension
        WHERE extname = 'pg_cron'
    ) THEN
        EXECUTE $query$
            SELECT count(*)
            FROM cron.job
            WHERE jobname = 'batch-result-retrieval'
              AND command = 'SELECT cron_fetch_batch_results();'
        $query$
        INTO legacy_job_count;

        IF legacy_job_count <> 0 THEN
            RAISE EXCEPTION 'Refusing to retire pg_cron while the retired provider job remains scheduled'
                USING ERRCODE = '55000',
                      HINT = 'Run 03_cron_batch_retrieval.sql successfully before this migration.';
        END IF;

        EXECUTE 'SELECT count(*) FROM cron.job'
        INTO remaining_job_count;
        IF remaining_job_count <> 0 THEN
            RAISE EXCEPTION 'Refusing to retire pg_cron while cron jobs remain'
                USING ERRCODE = '55000',
                      HINT = 'Migrate or remove operator-owned cron jobs before retiring the extension.';
        END IF;
    END IF;

    IF to_regprocedure('public.cron_fetch_batch_results()') IS NOT NULL
       OR to_regprocedure('public.import_batch_results_jsonl(uuid,text,text)') IS NOT NULL
       OR to_regprocedure('public.get_secret_value(text)') IS NOT NULL
       OR to_regprocedure('public.get_config_value(text)') IS NOT NULL THEN
        RAISE EXCEPTION 'Refusing to retire provider extensions while retired helper functions remain'
            USING ERRCODE = '55000',
                  HINT = 'Run 03_cron_batch_retrieval.sql successfully and review any substituted helper before retrying.';
    END IF;

    -- RESTRICT still removes objects that are extension members. Fail closed for
    -- unexpected table-like members before DROP EXTENSION can erase application
    -- state. pg_cron owns its expected relations inside the cron schema; http is
    -- not allowed to own an application table-like relation at this boundary.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_depend AS dep
        JOIN pg_catalog.pg_extension AS ext
          ON dep.refclassid = 'pg_catalog.pg_extension'::pg_catalog.regclass
         AND dep.refobjid = ext.oid
        JOIN pg_catalog.pg_class AS relation
          ON dep.classid = 'pg_catalog.pg_class'::pg_catalog.regclass
         AND dep.objid = relation.oid
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE ext.extname IN ('http', 'pg_cron')
          AND dep.deptype = 'e'
          AND dep.objsubid = 0
          AND dep.refobjsubid = 0
          AND relation.relkind IN ('r', 'p', 'f', 'm', 'v', 'S')
          AND (ext.extname = 'http' OR namespace.nspname <> 'cron')
    ) THEN
        RAISE EXCEPTION 'Refusing to retire provider extensions while unexpected relation members remain'
            USING ERRCODE = '55000',
                  HINT = 'Detach or migrate application-owned extension members before retrying.';
    END IF;

    -- Objects marked DEPENDS ON EXTENSION use an auto-extension dependency and
    -- are dropped with the referenced extension even under RESTRICT. Preserve
    -- them for explicit operator disposition instead of treating them as safe.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_depend AS dep
        JOIN pg_catalog.pg_extension AS ext
          ON dep.refclassid = 'pg_catalog.pg_extension'::pg_catalog.regclass
         AND dep.refobjid = ext.oid
        WHERE ext.extname IN ('http', 'pg_cron')
          AND dep.deptype = 'x'
          AND dep.refobjsubid = 0
    ) THEN
        RAISE EXCEPTION 'Refusing to retire provider extensions while explicit extension dependencies remain'
            USING ERRCODE = '55000',
                  HINT = 'Remove the DEPENDS ON EXTENSION relationship or migrate the dependent object before retrying.';
    END IF;
END
$$;

DROP EXTENSION IF EXISTS http RESTRICT;
DROP EXTENSION IF EXISTS pg_cron RESTRICT;

COMMIT;
