# Evaluation Harness Report

**Timestamp:** 2026-10-06T04:24:36Z  
**Model:** gemini-3.5-flash-lite  
**Total Questions:** 6  

## Key Metrics

- **Accuracy:** 16.7%
- **Consistency:** 66.7%
- **Answerability:** 100.0%
- **Resilience (Avg Retries):** 0.50 per question
- **Speed (p50 Latency):** 3687 ms
- **Speed (p95 Latency):** 57430 ms

## Question Breakdown

|   ID | Level   | Question                                              | Correct   | Consistent   | Avg Time   |   Avg Retries |
|------|---------|-------------------------------------------------------|-----------|--------------|------------|---------------|
|    1 | Easy    | List the active shops in Istanbul with their shop ... | ✗         | ✓            | 3333ms     |           0   |
|    2 | Easy    | How many phone campaigns are available for sale, b... | ✓         | ✓            | 3274ms     |           0   |
|    3 | Medium  | Which customer segment had the highest number of u... | ✗         | ✓            | 3208ms     |           0   |
|    4 | Medium  | Compare monthly gross adds and disconnections for ... | ✗         | ✗            | 7938ms     |           1.3 |
|    5 | Hard    | As of 28 August 2026, how many subscribers in the ... | ✗         | ✓            | 21157ms    |           0   |
|    6 | Hard    | For every disconnection in August 2026, which tari... | ✗         | ✗            | 9230ms     |           1.7 |
