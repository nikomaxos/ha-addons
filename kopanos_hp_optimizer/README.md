# Kopanos HP Optimizer (Home Assistant add-on)

Winter-long heat pump optimizer for Kopanos Home: per-cycle KPIs from HA history, randomized paired A/B
testing with OLS + 90% CI, and per-outdoor-temperature-zone autotuning of a **strict allowlist of 9 HA helpers**.
It never writes to the heat pump. See [DOCS.md](DOCS.md).

Development:
```bash
pip install -r requirements.txt pytest httpx pyyaml
pytest tests
```
