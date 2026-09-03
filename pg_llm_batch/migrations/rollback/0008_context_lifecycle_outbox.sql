-- SPDX-License-Identifier: Apache-2.0
-- Roll back the pg-owned lifecycle outbox without touching upstream authorities.

DO $$
BEGIN
    DROP POLICY IF EXISTS plc_llm_context_lifecycle_outbox_tenant_scope
        ON llm_context_lifecycle_outbox;
    DROP TABLE IF EXISTS llm_context_lifecycle_outbox;
END $$;
