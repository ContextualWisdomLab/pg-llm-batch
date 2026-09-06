-- SPDX-License-Identifier: Apache-2.0
-- Reject hidden row-admission authority on the canonical lifecycle outbox.

DO $$
DECLARE
    canonical_payload_check_expression TEXT;
    canonical_valid_time_check_expression TEXT;
    canonical_system_time_check_expression TEXT;
BEGIN
    PERFORM pg_catalog.set_config('search_path', 'pg_catalog, public, pg_temp', true);

    IF pg_catalog.to_regclass('public.llm_context_lifecycle_outbox') IS NULL THEN
        RAISE EXCEPTION 'lifecycle outbox relation is unavailable';
    END IF;

    -- RLS is final row-admission authority, not merely a migration-0008 side effect.
    -- A restore/operator can disable relation-level enforcement or replace the sole
    -- canonical policy under the same name after 0008 was recorded as applied. Final
    -- admission therefore proves both relation flags and the complete policy catalog
    -- identity without attempting to repair operator drift.
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS outbox_relation
        WHERE outbox_relation.oid =
              'public.llm_context_lifecycle_outbox'::pg_catalog.regclass
          AND outbox_relation.relrowsecurity
          AND outbox_relation.relforcerowsecurity
    ) OR (
        SELECT pg_catalog.count(*)
        FROM pg_catalog.pg_policy AS outbox_policy
        WHERE outbox_policy.polrelid =
              'public.llm_context_lifecycle_outbox'::pg_catalog.regclass
    ) OPERATOR(pg_catalog.<>) 1 OR NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policy AS outbox_policy
        WHERE outbox_policy.polrelid =
              'public.llm_context_lifecycle_outbox'::pg_catalog.regclass
          AND outbox_policy.polname OPERATOR(pg_catalog.=)
              'plc_llm_context_lifecycle_outbox_tenant_scope_canonical_v2'
          AND outbox_policy.polcmd OPERATOR(pg_catalog.=) '*'
          AND outbox_policy.polpermissive
          AND outbox_policy.polroles OPERATOR(pg_catalog.=) ARRAY[0::pg_catalog.oid]
          AND pg_catalog.pg_get_expr(
              outbox_policy.polqual,
              outbox_policy.polrelid,
              false
          ) OPERATOR(pg_catalog.=)
              '(tenant_scope = current_setting(''pg_llm_batch.tenant_scope''::text, true))'
          AND pg_catalog.pg_get_expr(
              outbox_policy.polwithcheck,
              outbox_policy.polrelid,
              false
          ) OPERATOR(pg_catalog.=)
              '(tenant_scope = current_setting(''pg_llm_batch.tenant_scope''::text, true))'
          AND NOT EXISTS (
              SELECT 1
              FROM pg_catalog.pg_depend AS unexpected_policy_dependency
              WHERE unexpected_policy_dependency.classid OPERATOR(pg_catalog.=)
                    'pg_catalog.pg_policy'::pg_catalog.regclass
                AND unexpected_policy_dependency.objid OPERATOR(pg_catalog.=)
                    outbox_policy.oid
                AND unexpected_policy_dependency.objsubid OPERATOR(pg_catalog.=) 0
                AND unexpected_policy_dependency.refobjsubid OPERATOR(pg_catalog.=) 0
                AND unexpected_policy_dependency.deptype::pg_catalog.text
                    OPERATOR(pg_catalog.=) 'n'
                AND (
                    (
                        unexpected_policy_dependency.refclassid OPERATOR(pg_catalog.=)
                            'pg_catalog.pg_proc'::pg_catalog.regclass
                        AND unexpected_policy_dependency.refobjid OPERATOR(pg_catalog.<>)
                            'pg_catalog.current_setting(pg_catalog.text,pg_catalog.bool)'::pg_catalog.regprocedure
                    )
                    OR (
                        unexpected_policy_dependency.refclassid OPERATOR(pg_catalog.=)
                            'pg_catalog.pg_operator'::pg_catalog.regclass
                        AND unexpected_policy_dependency.refobjid OPERATOR(pg_catalog.<>)
                            'pg_catalog.=(pg_catalog.text,pg_catalog.text)'::pg_catalog.regoperator
                    )
                )
          )
    ) THEN
        RAISE EXCEPTION 'unexpected lifecycle outbox row-admission authority';
    END IF;

    -- Table-attached programs are final row-admission authority too. Migration 0008
    -- rejects them while converging the schema, but an operator or restore can attach
    -- a user trigger or rewrite rule after 0008 was recorded as applied. Internal
    -- constraint triggers remain PostgreSQL-owned; every user trigger and every rule
    -- requires explicit reconciliation before this final admission gate can pass.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_trigger AS outbox_trigger
        WHERE outbox_trigger.tgrelid =
              'public.llm_context_lifecycle_outbox'::pg_catalog.regclass
          AND NOT outbox_trigger.tgisinternal
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_rewrite AS outbox_rule
        WHERE outbox_rule.ev_class =
              'public.llm_context_lifecycle_outbox'::pg_catalog.regclass
    ) THEN
        RAISE EXCEPTION 'unexpected lifecycle outbox row-admission authority';
    END IF;

    -- Package INSERTs intentionally omit the generated durable UUID and created-at
    -- timestamp, so those defaults execute on every new outbox row. A restore/operator
    -- can replace either default after migration 0008 was recorded as applied while
    -- leaving constraints, RLS, triggers, rules, and indexes unchanged. Final admission
    -- therefore re-proves exact PostgreSQL-core default authority and column shape.
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_attribute AS admission_attribute
        JOIN pg_catalog.pg_attrdef AS admission_default
          ON admission_default.adrelid = admission_attribute.attrelid
         AND admission_default.adnum = admission_attribute.attnum
        WHERE admission_attribute.attrelid =
              'public.llm_context_lifecycle_outbox'::pg_catalog.regclass
          AND admission_attribute.attname OPERATOR(pg_catalog.=) 'context_outbox_uuid'
          AND admission_attribute.attnum OPERATOR(pg_catalog.>) 0
          AND NOT admission_attribute.attisdropped
          AND admission_attribute.atttypid OPERATOR(pg_catalog.=)
              'pg_catalog.uuid'::pg_catalog.regtype
          AND admission_attribute.attnotnull
          AND admission_attribute.atthasdef
          AND admission_attribute.attgenerated OPERATOR(pg_catalog.=) ''
          AND admission_attribute.attidentity OPERATOR(pg_catalog.=) ''
          AND pg_catalog.pg_get_expr(
              admission_default.adbin,
              admission_default.adrelid,
              false
          ) OPERATOR(pg_catalog.=) 'gen_random_uuid()'
    ) OR NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_attribute AS admission_attribute
        JOIN pg_catalog.pg_attrdef AS admission_default
          ON admission_default.adrelid = admission_attribute.attrelid
         AND admission_default.adnum = admission_attribute.attnum
        WHERE admission_attribute.attrelid =
              'public.llm_context_lifecycle_outbox'::pg_catalog.regclass
          AND admission_attribute.attname OPERATOR(pg_catalog.=) 'created_at'
          AND admission_attribute.attnum OPERATOR(pg_catalog.>) 0
          AND NOT admission_attribute.attisdropped
          AND admission_attribute.atttypid OPERATOR(pg_catalog.=)
              'timestamp with time zone'::pg_catalog.regtype
          AND admission_attribute.attnotnull
          AND admission_attribute.atthasdef
          AND admission_attribute.attgenerated OPERATOR(pg_catalog.=) ''
          AND admission_attribute.attidentity OPERATOR(pg_catalog.=) ''
          AND pg_catalog.pg_get_expr(
              admission_default.adbin,
              admission_default.adrelid,
              false
          ) OPERATOR(pg_catalog.=) 'now()'
    ) THEN
        RAISE EXCEPTION 'unexpected lifecycle outbox row-admission authority';
    END IF;

    -- Migration 0009 is the final row-admission gate and must independently verify
    -- CHECK semantics even when migration 0008 was recorded as applied before later
    -- restore/operator drift. Derive parser-normalized canonical expressions from this
    -- PostgreSQL runtime instead of trusting names or version-sensitive hard-coded text.
    CREATE TEMPORARY TABLE pg_llm_batch_outbox_admission_probe_v1 (
        tenant_scope TEXT NOT NULL,
        evidence_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        tenant_scope_sha256 TEXT NOT NULL,
        subject_ref_sha256 TEXT NOT NULL,
        authority_ref_sha256 TEXT NOT NULL,
        origin_ref_sha256 TEXT NOT NULL,
        truth_status TEXT NOT NULL,
        valid_time TEXT NOT NULL,
        system_time TEXT NOT NULL,
        provenance_ref_sha256 TEXT NOT NULL,
        evidence_ref_sha256 TEXT NOT NULL,
        CONSTRAINT pg_llm_batch_outbox_payload_admission_probe_v1
            CHECK (
                tenant_scope ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
                AND evidence_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
                AND event_type ~ '^[a-z][a-z0-9._:-]{0,127}$'
                AND tenant_scope_sha256 ~ '^[0-9a-f]{64}$'
                AND subject_ref_sha256 ~ '^[0-9a-f]{64}$'
                AND authority_ref_sha256 ~ '^[0-9a-f]{64}$'
                AND origin_ref_sha256 ~ '^[0-9a-f]{64}$'
                AND truth_status IN (
                    'authoritative',
                    'observed',
                    'inferred',
                    'proposed',
                    'superseded',
                    'rejected'
                )
                AND provenance_ref_sha256 ~ '^[0-9a-f]{64}$'
                AND evidence_ref_sha256 ~ '^[0-9a-f]{64}$'
            ),
        CONSTRAINT pg_llm_batch_outbox_valid_time_admission_probe_v1
            CHECK (
                valid_time ~
                '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}([.]\d{6})?Z$'
                AND valid_time::timestamptz IS NOT NULL
                AND valid_time !~ '[.]000000Z$'
                AND valid_time = CASE
                    WHEN valid_time ~ '[.]' THEN
                        to_char(
                            valid_time::timestamptz AT TIME ZONE 'UTC',
                            'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
                        )
                    ELSE
                        to_char(
                            valid_time::timestamptz AT TIME ZONE 'UTC',
                            'YYYY-MM-DD"T"HH24:MI:SS"Z"'
                        )
                END
            ),
        CONSTRAINT pg_llm_batch_outbox_system_time_admission_probe_v1
            CHECK (
                system_time ~
                '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}([.]\d{6})?Z$'
                AND system_time::timestamptz IS NOT NULL
                AND system_time !~ '[.]000000Z$'
                AND system_time = CASE
                    WHEN system_time ~ '[.]' THEN
                        to_char(
                            system_time::timestamptz AT TIME ZONE 'UTC',
                            'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
                        )
                    ELSE
                        to_char(
                            system_time::timestamptz AT TIME ZONE 'UTC',
                            'YYYY-MM-DD"T"HH24:MI:SS"Z"'
                        )
                END
            )
    ) ON COMMIT DROP;

    SELECT pg_catalog.pg_get_expr(conbin, conrelid, false)
    INTO STRICT canonical_payload_check_expression
    FROM pg_catalog.pg_constraint
    WHERE conrelid = 'pg_temp.pg_llm_batch_outbox_admission_probe_v1'::pg_catalog.regclass
      AND conname = 'pg_llm_batch_outbox_payload_admission_probe_v1';

    SELECT pg_catalog.pg_get_expr(conbin, conrelid, false)
    INTO STRICT canonical_valid_time_check_expression
    FROM pg_catalog.pg_constraint
    WHERE conrelid = 'pg_temp.pg_llm_batch_outbox_admission_probe_v1'::pg_catalog.regclass
      AND conname = 'pg_llm_batch_outbox_valid_time_admission_probe_v1';

    SELECT pg_catalog.pg_get_expr(conbin, conrelid, false)
    INTO STRICT canonical_system_time_check_expression
    FROM pg_catalog.pg_constraint
    WHERE conrelid = 'pg_temp.pg_llm_batch_outbox_admission_probe_v1'::pg_catalog.regclass
      AND conname = 'pg_llm_batch_outbox_system_time_admission_probe_v1';

    DROP TABLE pg_temp.pg_llm_batch_outbox_admission_probe_v1;

    -- Migration 0008 has already converged and verified the five package-owned
    -- row-admission constraints. Any additional CHECK/FK/PK/UNIQUE/EXCLUDE object can
    -- narrow or redirect otherwise-valid writes, so unknown authority requires
    -- explicit operator reconciliation rather than package-owned deletion. Names alone
    -- are insufficient for CHECKs: a restore or operator can replace a canonical name
    -- with a different Boolean expression after migration 0008 was previously applied.
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
                  AND (
                      (
                          outbox_constraint.conname OPERATOR(pg_catalog.=)
                              'ck_llm_context_lifecycle_outbox_payload_canonical_v1'
                          AND pg_catalog.pg_get_expr(
                              outbox_constraint.conbin,
                              outbox_constraint.conrelid,
                              false
                          ) OPERATOR(pg_catalog.=) canonical_payload_check_expression
                      )
                      OR (
                          outbox_constraint.conname OPERATOR(pg_catalog.=)
                              'ck_llm_context_lifecycle_outbox_valid_time_canonical_v1'
                          AND pg_catalog.pg_get_expr(
                              outbox_constraint.conbin,
                              outbox_constraint.conrelid,
                              false
                          ) OPERATOR(pg_catalog.=) canonical_valid_time_check_expression
                      )
                      OR (
                          outbox_constraint.conname OPERATOR(pg_catalog.=)
                              'ck_llm_context_lifecycle_outbox_system_time_canonical_v1'
                          AND pg_catalog.pg_get_expr(
                              outbox_constraint.conbin,
                              outbox_constraint.conrelid,
                              false
                          ) OPERATOR(pg_catalog.=) canonical_system_time_check_expression
                      )
                  )
              )
          )
    ) THEN
        RAISE EXCEPTION 'unexpected lifecycle outbox row-admission authority';
    END IF;

    -- Index maintenance can execute more than explicit expressions/predicates. A
    -- user-defined operator class supplies access-method support functions that are
    -- invoked while maintaining even a plain non-unique column index. Accept only the
    -- default pg_catalog operator class for each exact indexed column type and access
    -- method. This keeps PostgreSQL-core simple-column indexes available without
    -- admitting operator-selected support-function authority. Unknown executable index
    -- semantics require operator reconciliation instead of package-owned deletion.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_index AS admission_index
        JOIN pg_catalog.pg_class AS admission_index_relation
          ON admission_index_relation.oid = admission_index.indexrelid
        WHERE admission_index.indrelid =
              'public.llm_context_lifecycle_outbox'::pg_catalog.regclass
          AND (
              admission_index.indexprs IS NOT NULL
              OR admission_index.indpred IS NOT NULL
              OR EXISTS (
                  SELECT 1
                  FROM pg_catalog.generate_series(
                      0,
                      admission_index.indnkeyatts - 1
                  ) AS key_position(position)
                  WHERE NOT EXISTS (
                      SELECT 1
                      FROM pg_catalog.pg_opclass AS admission_opclass
                      JOIN pg_catalog.pg_attribute AS actual_attribute
                        ON actual_attribute.attrelid = admission_index.indrelid
                       AND actual_attribute.attnum =
                           admission_index.indkey[key_position.position]
                       AND actual_attribute.attnum OPERATOR(pg_catalog.>) 0
                       AND NOT actual_attribute.attisdropped
                      WHERE admission_opclass.oid =
                            admission_index.indclass[key_position.position]
                        AND admission_opclass.opcmethod = admission_index_relation.relam
                        AND admission_opclass.opcnamespace =
                            'pg_catalog'::pg_catalog.regnamespace
                        AND admission_opclass.opcdefault
                        AND admission_opclass.opcintype = actual_attribute.atttypid
                  )
              )
              OR (
                  admission_index.indisunique
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
              )
          )
    ) THEN
        RAISE EXCEPTION 'unexpected lifecycle outbox row-admission authority';
    END IF;
END $$;