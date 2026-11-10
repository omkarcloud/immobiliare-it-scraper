FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

COPY requirements.txt .

RUN python -m pip install --no-cache-dir -r requirements.txt

RUN mkdir app
WORKDIR /app
COPY . /app

EXPOSE 8000

# No browser needed — the scraper reads immobiliare.it's own JSON and server-rendered pages over plain HTTP with real browser TLS fingerprints.
CMD ["python", "run.py"]
