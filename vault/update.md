
- [2026-09-25]
  - Updated Add-on UI configuration options from `gemini-2.5-flash`/`pro` to `"3.8 flash high"` and `"3.1 pro high"`.
  - Migrated backend SDK in `server.py` from deprecated `google.generativeai` to the new `google-genai` official SDK.
  - Translated API tool definitions to Python dicts supported by `google-genai` and updated client initialization.
  - Updated Add-on configuration and restarted docker container using Supervisor APIs (`/options`, `/rebuild`, `/start`), successfully resolving the `FutureWarning`.
