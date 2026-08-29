"""
pytest configuration — sets required environment variables before any app
module is imported, so unit tests don't need a real database or OpenAI key.
"""
import os

# Set required env vars before the app settings module is imported
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/testdb")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-key")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
