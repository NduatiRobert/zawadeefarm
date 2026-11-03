FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m farm && mkdir -p /app/farm/instance && chown -R farm /app
USER farm
EXPOSE 8000
CMD ["sh", "-c", "gunicorn -w ${WEB_CONCURRENCY:-3} --preload -b 0.0.0.0:${PORT:-8000} --timeout 60 wsgi:app"]
