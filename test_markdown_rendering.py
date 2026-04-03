"""Test markdown rendering in chat responses."""

test_responses = [
    """The company shows strong **profitability** with a net profit margin of **15.85%** and ROE of **18.5%**.

Key metrics:
- **ROE**: 18.5% (↑2.1% YoY)
- **ROA**: 6.2% (↑0.8% YoY)  
- **Operating Margin**: 22.3%

This indicates efficient asset utilization and healthy earnings generation.""",

    """Here's the **liquidity outlook**:

| Metric | Value | Status |
|--------|-------|--------|
| **Cash Ratio** | 0.85 | Excellent |
| **Current Ratio** | 1.2 | Good |
| **Working Capital** | High | Positive |

The company maintains strong short-term liquidity position with adequate cash reserves.""",

    """Regarding **growth trends**, the company demonstrates:

1. **Sales Growth**: CAGR of 12.5% over 3 years
2. **Profit Growth**: CAGR of 18.2% over 3 years
3. **Expansion**: Consistent YoY increases

**Note**: Growth has been **accelerating** in recent quarters, particularly in high-margin segments.""",
]

print("=" * 70)
print("MARKDOWN RENDERING TEST - Chat Response Examples")
print("=" * 70)

for i, response in enumerate(test_responses, 1):
    print(f"\n[Response {i}]")
    print(response)
    print("-" * 70)

print("\nMarkdown features being tested:")
print("✓ Bold text using **text**")
print("✓ Lists using - or 1.")
print("✓ Tables using | | |")
print("✓ Inline formatting and emphasis")
