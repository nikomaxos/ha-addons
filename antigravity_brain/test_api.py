import os
from fastapi.testclient import TestClient
from server import app

client = TestClient(app)

response = client.post(
    "/v1/chat/completions",
    json={
        "model": "3.8 flash high",
        "messages": [
            {"role": "user", "content": "What is the weather?"}
        ]
    },
)
print("Status Code:", response.status_code)
print("Response JSON:", response.json())
