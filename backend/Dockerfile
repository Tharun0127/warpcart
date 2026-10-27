FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
# Dev requirements (pytest, locust) are installed too so tests and benchmarks
# run inside the same container as the API, with no Windows quirks.
RUN pip install -r requirements.txt -r requirements-dev.txt

COPY . .
# Guard against CRLF line endings if the repo was checked out on Windows.
RUN sed -i 's/\r$//' /app/entrypoint.sh

EXPOSE 8000
CMD ["sh", "/app/entrypoint.sh"]
