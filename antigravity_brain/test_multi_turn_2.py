from google import genai
import json

api_key = 'YOUR_API_KEY_HERE'
client = genai.Client(api_key=api_key)

GEMINI_TOOLS = [{
    "function_declarations": [
        {
            "name": "query_database",
            "description": "desc",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "query": {"type": "STRING"}
                },
                "required": ["query"]
            }
        }
    ]
}]

history = [{'role': 'user', 'parts': [{'text': 'query database to get users'}]}]

response = client.models.generate_content(
    model='gemini-3.8-flash',
    contents=history,
    config={'tools': GEMINI_TOOLS}
)

candidate_content = response.candidates[0].content
history.append(candidate_content)

fc = None
for part in candidate_content.parts:
    if hasattr(part, 'function_call') and part.function_call:
        fc = part.function_call
        break

if fc:
    # Use snake_case as in server.py
    history.append({
        "role": "user",
        "parts": [{
            "function_response": {
                "name": fc.name,
                "response": {"result": "ok"}
            }
        }]
    })

    # Call again
    response2 = client.models.generate_content(
        model='gemini-3.8-flash',
        contents=history,
        config={'tools': GEMINI_TOOLS}
    )
    print("Final response:", response2.text)
else:
    print("No function called.")
