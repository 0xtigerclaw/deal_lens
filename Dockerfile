FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEALLENS_ROOT=/app \
    PORT=8080

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY jurisdictions ./jurisdictions
COPY fixtures ./fixtures
COPY examples ./examples
COPY policy.yaml policy.owner_operator.yaml ./

RUN pip install --no-cache-dir .

EXPOSE 8080

CMD ["sh", "-c", "uvicorn deallens.web:app --host 0.0.0.0 --port ${PORT}"]
