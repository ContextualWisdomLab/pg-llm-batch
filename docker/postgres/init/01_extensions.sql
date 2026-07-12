-- SPDX-License-Identifier: Apache-2.0
-- PostgreSQL extensions required by pg-llm-batch.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_cron;
CREATE EXTENSION IF NOT EXISTS http;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'pg_tiktoken') THEN
        CREATE EXTENSION IF NOT EXISTS pg_tiktoken;
    END IF;
END $$;
