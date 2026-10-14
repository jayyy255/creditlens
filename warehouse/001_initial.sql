-- CreditLens analytical mart. Apply through scripts/load_warehouse.py.
CREATE SCHEMA IF NOT EXISTS creditlens;
CREATE TABLE IF NOT EXISTS creditlens.schema_versions (
    version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS creditlens.borrowers (
    sk_id_curr bigint PRIMARY KEY,
    target smallint NOT NULL CHECK (target IN (0, 1)),
    amt_income_total double precision,
    amt_credit double precision,
    amt_annuity double precision,
    credit_to_income double precision,
    annuity_to_income double precision,
    age_band text,
    code_gender text,
    name_income_type text,
    late_payment_mean double precision,
    bureau_debt_mean double precision,
    data_kind text NOT NULL CHECK (data_kind IN ('synthetic', 'home-credit'))
);
CREATE TABLE IF NOT EXISTS creditlens.validation_scores (
    sk_id_curr bigint PRIMARY KEY REFERENCES creditlens.borrowers,
    probability double precision NOT NULL CHECK (probability BETWEEN 0 AND 1)
);
CREATE INDEX IF NOT EXISTS borrowers_segment_idx ON creditlens.borrowers(name_income_type, age_band);
CREATE INDEX IF NOT EXISTS scores_probability_idx ON creditlens.validation_scores(probability);
CREATE MATERIALIZED VIEW IF NOT EXISTS creditlens.segment_risk AS
SELECT name_income_type, age_band, data_kind, count(*) AS applications,
       sum(target) AS difficulty_events, avg(target) AS event_rate,
       sum(amt_credit) AS requested_credit,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY credit_to_income) AS median_credit_to_income
FROM creditlens.borrowers
GROUP BY name_income_type, age_band, data_kind;
CREATE UNIQUE INDEX IF NOT EXISTS segment_risk_key
ON creditlens.segment_risk(name_income_type, age_band, data_kind);
INSERT INTO creditlens.schema_versions(version) VALUES (1) ON CONFLICT DO NOTHING;
