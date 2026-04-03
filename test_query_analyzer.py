"""Test the QueryAnalyzer implementation."""
from llm.query_analyzer import get_analyzer
import json

# Load test data
with open('data/processed/analysis.json') as f:
    data = json.load(f)

analyzer = get_analyzer()

# Test queries
test_queries = [
    'What is the net profit margin trend?',
    'Tell me about P/E ratio',
    'How is liquidity looking?',
    'Tell me about the company',
    'What about efficiency and growth?',
]

print('=' * 70)
print('QUERY ANALYZER TEST RESULTS')
print('=' * 70)

total_full_tokens = len(json.dumps(data, indent=2).split()) * 1.3  # Baseline

for query in test_queries:
    context, metadata = analyzer.process_query(query, data)
    token_estimate = len(context.split()) * 1.3
    reduction_pct = (1 - token_estimate / total_full_tokens) * 100
    
    print(f'\nQuery: "{query}"')
    print(f'  Categories: {metadata["categories"]}')
    print(f'  Confidence: {metadata["confidence"]:.1%}')
    print(f'  Type: {metadata["context_type"]}')
    print(f'  Est. tokens: {token_estimate:.0f} (vs {total_full_tokens:.0f} full)')
    print(f'  Token reduction: {reduction_pct:.1f}%')
    print(f'  Context length: {len(context)} chars')

print('\n' + '=' * 70)
print('BASELINE (Full JSON dump):')
print(f'  Tokens (estimated): {total_full_tokens:.0f}')
print('=' * 70)
