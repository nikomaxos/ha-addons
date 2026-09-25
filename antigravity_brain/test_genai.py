import os
from google import genai

client = genai.Client(api_key="YOUR_API_KEY_HERE")
try:
    res = client.models.embed_content(
        model='text-embedding-004',
        contents='test text'
    )
    if hasattr(res, 'embeddings'):
        print(type(res.embeddings[0]))
        print(dir(res.embeddings[0]))
        if hasattr(res.embeddings[0], 'values'):
            print("HAS VALUES")
    else:
        print("NO EMBEDDINGS")
except Exception as e:
    print(e)
