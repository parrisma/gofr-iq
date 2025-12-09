# News Impact Ranking Scale

## Tier Definitions

| Tier | Percentile | Label | Typical Absolute Move | Event Types |
|------|------------|-------|----------------------|-------------|
| **Platinum** | Top 1% | Market-moving | >5% single-stock, >2% sector | Earnings shock (>20% beat/miss), M&A announcement, fraud/accounting scandal, CEO sudden departure, FDA approval/rejection, major litigation outcome |
| **Gold** | Next 2% (1-3%) | High Impact | 3-5% stock, 1-2% sector | Guidance revision, activist stake disclosure, credit rating change (2+ notches), major contract win/loss, dividend cut/initiation, index add/delete |
| **Silver** | Next 10% (3-13%) | Notable | 1-3% stock, 0.5-1% sector | Analyst upgrade/downgrade (top-tier), insider transactions (>$1M), secondary offering, management change (CFO/COO), regulatory approval (non-binary), peer earnings read-through |
| **Bronze** | Next 20% (13-33%) | Moderate | 0.5-1% stock | Conference presentation, patent grant, small contract, routine filing, industry data point, competitor news |
| **Standard** | Bottom 67% | Routine | <0.5% | Press releases, minor personnel, marketing announcements, routine regulatory filings |

---

## Calibration Benchmarks (Empirical)

Based on academic studies and market microstructure research:

| Event Category | Median Absolute Abnormal Return | 90th Percentile | Source |
|----------------|--------------------------------|-----------------|--------|
| Earnings surprises | 3.2% (per 1% SUE) | 8-12% | Ball & Brown, Post-earnings drift literature |
| M&A target announcement | 15-25% | 40%+ | Andrade et al. (2001) |
| Analyst revision | 1.5-2.5% | 5% | Womack (1996), Barber et al. |
| Index inclusion | 3-5% (S&P 500) | 8% | Shleifer (1986), Chen et al. |
| Dividend initiation | 3-4% | 7% | Michaely et al. (1995) |
| CEO turnover (forced) | 2-4% | 10% | Warner et al. (1988) |
| Activist 13D filing | 5-7% | 15% | Brav et al. (2008) |
| Credit downgrade | 1-2% (equity) | 5% | Hand, Holthausen, Leftwich |
| FDA drug approval | 5-10% (biotech) | 30%+ | Event study literature |
| SEC enforcement | 8-12% | 25% | Karpoff et al. |

---

## Scoring Formula

```
Impact Score = w1 × |Price Move| + w2 × Volume Spike + w3 × Options IV Jump + w4 × News Velocity

Where:
- |Price Move| = absolute return vs. market (beta-adjusted)
- Volume Spike = volume / 20-day avg volume
- Options IV Jump = change in ATM implied vol
- News Velocity = articles in first hour / baseline

Weights (calibrated):
- w1 = 0.50 (price is king)
- w2 = 0.20 (confirms real interest)
- w3 = 0.20 (forward-looking uncertainty)
- w4 = 0.10 (media attention proxy)
```

---

## Decay Function

News impact decays—recency matters:

```
Relevance(t) = Impact Score × e^(-λt)

λ = 0.15 per day (half-life ≈ 4.6 days)

Platinum events: λ = 0.05 (slower decay, ~14 day half-life)
Standard events: λ = 0.30 (fast decay, ~2.3 day half-life)
```

---

## Client-Specific Thresholds

| Client Type | Platinum Threshold | Alert Frequency Target |
|-------------|-------------------|----------------------|
| Hedge Fund (L/S) | >3% move | 5-10/day |
| Long-Only AM | >5% move | 2-5/day |
| Quant/Systematic | >2 std dev | Real-time feed |
| Pension/SWF | >Sector-level | Weekly digest |
