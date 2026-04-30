FROM python:3.14-slim

WORKDIR /app

# Install uv package manager
RUN pip install --no-cache-dir uv

# Copy dependency files
COPY pyproject.toml uv.lock* ./

# Install dependencies using uv
RUN uv pip install --system --no-cache -r pyproject.toml

# Copy application code
COPY bot/ ./bot/
COPY alembic.ini ./
COPY migrations/ ./migrations/

# Compile locale files
RUN uv run pybabel compile -d bot/locales -D messages -f

# Expose health check port
EXPOSE 8080

# Run migrations and start bot
CMD ["sh", "-c", "alembic upgrade head && python -m bot"]
