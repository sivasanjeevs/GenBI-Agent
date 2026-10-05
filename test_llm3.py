from app.llm import _call_gemini_raw
for model in ["gemini-3.8-pro", "gemini-3.6-pro", "gemini-1.5-flash", "gemini-1.5-pro"]:
    try:
        resp = _call_gemini_raw("Hello", model=model)
        print(f"SUCCESS {model}:", resp[:20])
    except Exception as e:
        print(f"FAILED {model}:", str(e)[:100])
