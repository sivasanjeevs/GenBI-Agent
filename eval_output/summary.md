# Evaluation Harness Report

**Timestamp:** 2026-10-06T05:39:40Z  
**Model:** gemini-3.5-flash-lite  
**Total Questions:** 6  

## Key Metrics

- **Accuracy:** 16.7%
- **Consistency:** 66.7%
- **Answerability:** 100.0%
- **Resilience (Avg Retries):** 0.39 per question
- **Speed (p50 Latency):** 3911 ms
- **Speed (p95 Latency):** 12186 ms

## Question Breakdown

|   ID | Level   | Question                                              | Correct   | Consistent   | Avg Time   |   Avg Retries |
|------|---------|-------------------------------------------------------|-----------|--------------|------------|---------------|
|    1 | Easy    | List the active shops in Istanbul with their shop ... | ✗         | ✓            | 3885ms     |           0   |
|    2 | Easy    | How many phone campaigns are available for sale, b... | ✓         | ✓            | 3480ms     |           0   |
|    3 | Medium  | Which customer segment had the highest number of u... | ✗         | ✓            | 3515ms     |           0   |
|    4 | Medium  | Compare monthly gross adds and disconnections for ... | ✗         | ✗            | 9284ms     |           1   |
|    5 | Hard    | As of 28 August 2026, how many subscribers in the ... | ✗         | ✓            | 3857ms     |           0   |
|    6 | Hard    | For every disconnection in August 2026, which tari... | ✗         | ✗            | 8567ms     |           1.3 |
