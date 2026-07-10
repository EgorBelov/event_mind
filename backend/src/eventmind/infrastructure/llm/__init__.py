"""LLM Gateway: цепочка провайдеров (Gemini→Groq70b→Groq8b) за портом.

Circuit-breaker + per-provider cooldown портированы из
`legacy/app/agents/recommendation/llm.py`, очищены от module-глобалов и
переведены на async.
"""
