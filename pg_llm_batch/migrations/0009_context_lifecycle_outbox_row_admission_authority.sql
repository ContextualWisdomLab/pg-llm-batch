-- SPDX-License-Identifier: Apache-2.0
-- Reject hidden row-admission authority on the canonical lifecycle outbox.

DO $$
BEGIN
    PERFORM pg_catalog.set_config('search_path', 'pg_catalog, public, pg_temp', true);

    IF pg_catalog.to_regclass('public.llm_context_lifecycle_outbox') IS NULL THEN
        RAISE EXCEPTION 'lifecycle outbox relation is unavailable';
    END IF;

    -- Migration 0008 has already converged and verified the five package-owned
    -- row-admission constraints. Any additional CHECK/FK/PK/UNIQUE/EXCLUDE object can
    -- narrow or redirect otherwise-valid writes, so unknown authority requires
    -- explicit operator reconciliation rather than package-owned deletion.
    IF (
        SELECT pg_catalog.count(*)
        FROM pg_catalog.pg_constraint AS outbox_constraint
        WHERE outbox_constraint.conrelid =
              'public.llm_context_lifecycle_outbox'::pg_catalog.regclass
          AND outbox_constraint.contype IN ('c', 'f', 'p', 'u', 'x')
    ) OPERATOR(pg_catalog.<>) 5 OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_constraint AS outbox_constraint
        WHERE outbox_constraint.conrelid =
              'public.llm_context_lifecycle_outbox'::pg_catalog.regclass
          AND outbox_constraint.contype IN ('c', 'f', 'p', 'u', 'x')
          AND NOT (
              (
                  outbox_constraint.contype OPERATOR(pg_catalog.=) 'p'
                  AND outbox_constraint.convalidated
                  AND NOT outbox_constraint.condeferrable
                  AND NOT outbox_constraint.condeferred
                  AND outbox_constraint.conkey OPERATOR(pg_catalog.=) ARRAY[
                      (
                          SELECT actual.attnum::pg_catalog.int2
                          FROM pg_catalog.pg_attribute AS actual
                          WHERE actual.attrelid =
                                'public.llm_context_lifecycle_outbox'::pg_catalog.regclass
                            AND actual.attname OPERATOR(pg_catalog.=) 'context_outbox_uuid'
                            AND actual.attnum OPERATOR(pg_catalog.>) 0
                            AND NOT actual.attisdropped
                      )
                  ]
              )
              OR (
                  outbox_constraint.contype OPERATOR(pg_catalog.=) 'u'
                  AND outbox_constraint.conname OPERATOR(pg_catalog.=)
                      'uq_llm_context_lifecycle_outbox_tenant_evidence'
                  AND outbox_constraint.convalidated
                  AND NOT outbox_constraint.condeferrable
                  AND NOT outbox_constraint.condeferred
                  AND outbox_constraint.conkey OPERATOR(pg_catalog.=) ARRAY[
                      (
                          SELECT actual.attnum::pg_catalog.int2
                          FROM pg_catalog.pg_attribute AS actual
                          WHERE actual.attrelid =
                                'public.llm_context_lifecycle_outbox'::pg_catalog.regclass
                            AND actual.attname OPERATOR(pg_catalog.=) 'tenant_scope'
                            AND actual.attnum OPERATOR(pg_catalog.>) 0
                            AND NOT actual.attisdropped
                      ),
                      (
                          SELECT actual.attnum::pg_catalog.int2
                          FROM pg_catalog.pg_attribute AS actual
                          WHERE actual.attrelid =
                                'public.llm_context_lifecycle_outbox'::pg_catalog.regclass
                            AND actual.attname OPERATOR(pg_catalog.=) 'evidence_id'
                            AND actual.attnum OPERATOR(pg_catalog.>) 0
                            AND NOT actual.attisdropped
                      )
                  ]
              )
              OR (
                  outbox_constraint.contype OPERATOR(pg_catalog.=) 'c'
                  AND outbox_constraint.convalidated
                  AND NOT outbox_constraint.connoinherit
                  AND outbox_constraint.conname IN (
                      'ck_llm_context_lifecycle_outbox_payload_canonical_v1',
                      'ck_llm_context_lifecycle_outbox_valid_time_canonical_v1',
                      'ck_llm_context_lifecycle_outbox_system_time_canonical_v1'
                  )
              )
          )
    ) THEN
        RAISE EXCEPTION 'unexpected lifecycle outbox row-admission authority';
    END IF;

    -- CREATE UNIQUE INDEX does not create a pg_constraint row, but it still rejects
    -- duplicate writes. Permit only the indexes backing the exact canonical PK and
    -- tenant/evidence replay constraint verified above.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_index AS admission_index
        WHERE admission_index.indrelid =
              'public.llm_context_lifecycle_outbox'::pg_catalog.regclass
          AND admission_index.indisunique
          AND NOT EXISTS (
              SELECT 1
              FROM pg_catalog.pg_constraint AS canonical_constraint
              WHERE canonical_constraint.conrelid = admission_index.indrelid
                AND canonical_constraint.conindid = admission_index.indexrelid
                AND (
                    (
                        canonical_constraint.contype OPERATOR(pg_catalog.=) 'p'
                        AND canonical_constraint.convalidated
                        AND NOT canonical_constraint.condeferrable
                        AND NOT canonical_constraint.condeferred
                        AND canonical_constraint.conkey OPERATOR(pg_catalog.=) ARRAY[
                            (
                                SELECT actual.attnum::pg_catalog.int2
                                FROM pg_catalog.pg_attribute AS actual
                                WHERE actual.attrelid = admission_index.indrelid
                                  AND actual.attname OPERATOR(pg_catalog.=)
                                      'context_outbox_uuid'
                                  AND actual.attnum OPERATOR(pg_catalog.>) 0
                                  AND NOT actual.attisdropped
                            )
                        ]
                    )
                    OR (
                        canonical_constraint.contype OPERATOR(pg_catalog.=) 'u'
                        AND canonical_constraint.conname OPERATOR(pg_catalog.=)
                            'uq_llm_context_lifecycle_outbox_tenant_evidence'
                        AND canonical_constraint.convalidated
                        AND NOT canonical_constraint.condeferrable
                        AND NOT canonical_constraint.condeferred
                        AND canonical_constraint.conkey OPERATOR(pg_catalog.=) ARRAY[
                            (
                                SELECT actual.attnum::pg_catalog.int2
                                FROM pg_catalog.pg_attribute AS actual
                                WHERE actual.attrelid = admission_index.indrelid
                                  AND actual.attname OPERATOR(pg_catalog.=) 'tenant_scope'
                                  AND actual.attnum OPERATOR(pg_catalog.>) 0
                                  AND NOT actual.attisdropped
                            ),
                            (
                                SELECT actual.attnum::pg_catalog.int2
                                FROM pg_catalog.pg_attribute AS actual
                                WHERE actual.attrelid = admission_index.indrelid
                                  AND actual.attname OPERATOR(pg_catalog.=) 'evidence_id'
                                  AND actual.attnum OPERATOR(pg_catalog.>) 0
                                  AND NOT actual.attisdropped
                            )
                        ]
                    )
                )
          )
    ) THEN
        RAISE EXCEPTION 'unexpected lifecycle outbox row-admission authority';
    END IF;
END $$;
