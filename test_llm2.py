from app.llm import _call_gemini_raw
try:
    resp = _call_gemini_raw("Hello", model="gemini-3.6-flash")
    print("SUCCESS 3.6-flash:", resp[:20])
except Exception as e:
    print("FAILED 3.6-flash:", e)
