-- SPDX-License-Identifier: Apache-2.0
-- PostgreSQL extensions required by fresh pg-llm-batch databases.
--
-- pg_cron and http are intentionally not created for new databases. The retired
-- legacy SQL provider retriever used those capabilities; provider I/O now belongs
-- to the validated Python client boundary. Image packages remain temporarily for
-- existing-volume compatibility and cleanup of previously installed extensions.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'pg_tiktoken') THEN
        CREATE EXTENSION IF NOT EXISTS pg_tiktoken;
    END IF;
END $$;
