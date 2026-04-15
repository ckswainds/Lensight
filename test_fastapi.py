import asyncio
from fastapi.testclient import TestClient
from backend.main import app
from io import BytesIO

client = TestClient(app)

res = client.post("/api/upload", files={"excel_file": ("test.xlsx", b"dummy content")})
print("STATUS:", res.status_code)
print("JSON:", res.text)
