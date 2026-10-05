import asyncio
from app.llm import _get_genai_client
from pydantic import BaseModel

class Person(BaseModel):
    name: str
    age: int

client, types = _get_genai_client()
schema = Person.model_json_schema()
def strip_ap(d):
    if isinstance(d, dict):
        d.pop("additionalProperties", None)
        for v in d.values():
            strip_ap(v)
    elif isinstance(d, list):
        for i in d:
            strip_ap(i)
strip_ap(schema)

config = types.GenerateContentConfig(
    response_mime_type="application/json",
    response_schema=schema,
    temperature=0.0
)
resp = client.models.generate_content(
    model="gemini-3.8-flash",
    contents="John is 30 years old",
    config=config
)
print(resp.text)
