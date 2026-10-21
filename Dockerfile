FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app \
    && mkdir -p /app/media /app/staticfiles && chown -R app:app /app

COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt "psycopg[binary]>=3.1" "gunicorn>=22.0" "whitenoise>=6.6"

COPY --chown=app:app . .

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/').status==200 else 1)"

# Migrates on start; SEED_DEMO_ON_START=true also loads the idempotent demo data (used by the
# Render blueprint, where the free plan has no shell).
CMD ["sh", "-c", "python manage.py migrate --noinput && if [ \"$SEED_DEMO_ON_START\" = true ]; then python manage.py seed_demo; fi && gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 3 --access-logfile -"]
