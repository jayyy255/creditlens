-- Segment concentration, event rate and portfolio contribution using CTEs/windows.
WITH segments AS (
    SELECT name_income_type, count(*) AS applications, sum(target) AS events,
           avg(target) AS event_rate, sum(amt_credit) AS requested_credit
    FROM creditlens.borrowers GROUP BY name_income_type
)
SELECT *, applications::numeric / sum(applications) OVER () AS application_share,
       requested_credit / NULLIF(sum(requested_credit) OVER (), 0) AS credit_share,
       dense_rank() OVER (ORDER BY event_rate DESC) AS event_rate_rank
FROM segments ORDER BY event_rate DESC;

-- Risk deciles on the policy validation sample, never the final test population.
WITH ranked AS (
    SELECT b.*, s.probability, ntile(10) OVER (ORDER BY s.probability, b.sk_id_curr) AS risk_decile
    FROM creditlens.borrowers b JOIN creditlens.validation_scores s USING (sk_id_curr)
)
SELECT risk_decile, count(*) AS applicants, avg(probability) AS predicted_risk,
       avg(target) AS observed_event_rate,
       count(*) FILTER (WHERE late_payment_mean > 0) AS borrowers_with_late_payment_records
FROM ranked GROUP BY risk_decile ORDER BY risk_decile;

-- Hypothetical policy frontier. Every metric derives from validation scores.
WITH thresholds AS (SELECT generate_series(0, 100, 5) / 100.0 AS threshold),
population AS (SELECT count(*)::numeric AS n FROM creditlens.validation_scores)
SELECT t.threshold, count(s.sk_id_curr) AS accepted,
       count(s.sk_id_curr) / NULLIF(p.n, 0) AS approval_rate,
       avg(s.probability) AS average_predicted_risk,
       coalesce(sum(s.probability), 0) AS expected_difficulty_events
FROM thresholds t CROSS JOIN population p
LEFT JOIN creditlens.validation_scores s ON s.probability <= t.threshold
GROUP BY t.threshold, p.n ORDER BY t.threshold;

-- Diagnose performance on a loaded database; timings depend on data/host.
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM creditlens.borrowers WHERE name_income_type = 'Working' AND age_band = '30–39';
