from llm.orchestrator import LLMOrchestrator

def main():
    print("Testing LLM Orchestrator with Gemini...")
    
    # Dummy mock data 
    dummy_data = {
        "company": "Tech Corp India",
        "ratios": {
            "ROCE": "15.4%",
            "Debt_to_Equity": "0.4",
            "Current_Ratio": "1.8"
        },
        "trends": {
            "Revenue_YoY": "+12%",
            "Net_Profit_YoY": "+8%"
        }
    }
    
    dummy_context = "Management recently guided for a softer Q4 due to macro headwinds in European markets, but domestic demand remains strong."
    
    try:
        orchestrator = LLMOrchestrator()
        result = orchestrator.analyze_company(data=dummy_data, rag_context=dummy_context)
        print("\n--- RESULTS ---\n")
        print(result)
        print("\n--- SUCCESS ---")
    except Exception as e:
        print(f"\n--- ERROR ---\n{e}")

if __name__ == "__main__":
    main()
