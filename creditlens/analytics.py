"""Descriptive portfolio statistics and explicitly hypothetical policy estimates."""

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency


def interval(events: int, n: int) -> list[float] | None:
    """95% Wilson score interval for a binomial proportion."""
    if n == 0:
        return None
    p, z = events / n, 1.959963984540054
    center = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [max(0., float(center - half)), min(1., float(center + half))]


def portfolio(frame: pd.DataFrame) -> dict:
    n, events = len(frame), int(frame.TARGET.sum())
    return {"applications": n, "events": events, "event_rate": events / n if n else None,
            "event_rate_ci95": interval(events, n),
            "requested_credit": float(frame.AMT_CREDIT.sum()),
            "median_income": float(frame.AMT_INCOME_TOTAL.median()) if n else None,
            "median_credit_to_income": float(frame.credit_to_income.median()) if n and frame.credit_to_income.notna().any() else None}


def segments(frame: pd.DataFrame, column: str) -> list[dict]:
    results = []
    for name, group in frame.groupby(column, observed=True, dropna=False):
        row = portfolio(group)
        row["segment"] = str(name)
        results.append(row)
    return results


def association(frame: pd.DataFrame, column: str) -> dict:
    table = pd.crosstab(frame[column].fillna("Unknown"), frame.TARGET)
    if min(table.shape) < 2:
        return {"column": column, "available": False}
    statistic, p, df, expected = chi2_contingency(table)
    return {"column": column, "available": True, "chi_squared": float(statistic),
            "p_value": float(p), "degrees_of_freedom": int(df),
            "minimum_expected_count": float(expected.min()),
            "reliable_asymptotic_counts": bool((expected >= 5).all()),
            "interpretation": "Unadjusted observational association; no causal or independent-effect claim. Exploratory tests are not adjusted for multiple comparisons."}


def simulate(scores: pd.DataFrame, threshold: float) -> dict:
    if not np.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("Threshold must be between 0 and 1.")
    if scores.empty:
        raise ValueError("Simulation requires a non-empty validation population.")
    accepted = scores.loc[scores.probability <= threshold]
    return {"threshold": threshold, "population": len(scores), "accepted": len(accepted),
            "approval_rate": len(accepted) / len(scores),
            "average_predicted_risk": float(accepted.probability.mean()) if len(accepted) else None,
            "expected_difficulty_events": float(accepted.probability.sum()),
            "requested_credit_accepted": float(accepted.AMT_CREDIT.sum()),
            "historical_event_rate_accepted": float(accepted.TARGET.mean()) if len(accepted) else None,
            "disclaimer": "Hypothetical validation-set selection. Expected events are sums of calibrated model probabilities, not realized defaults, credit losses, or causal policy impact."}
