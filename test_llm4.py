from app.llm import _call_gemini_raw
for model in ["gemini-pro", "gemini-flash", "gemini-4.0-flash", "gemini-3.5-flash", "gemini-3.7-flash", "gemini-4.0-pro"]:
    try:
        resp = _call_gemini_raw("Hello", model=model)
        print(f"SUCCESS {model}:", resp[:20])
    except Exception as e:
        print(f"FAILED {model}:", str(e)[:100])
