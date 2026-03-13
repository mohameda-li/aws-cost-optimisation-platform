FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/flaskAPP/web

COPY flaskAPP/web/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY . /app

EXPOSE 5000

# Production-style entrypoint (still fine for local dev)
CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]
