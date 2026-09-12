FROM node:22-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
COPY --from=frontend /build/frontend/dist ./frontend/dist
RUN mkdir -p /app/data

EXPOSE 8000
# --no-proxy-headers: quem interpreta X-Forwarded-For é a aplicação, via
# TRUSTED_PROXY_IPS. O uvicorn faz isso por padrão com uma política de
# confiança própria (só 127.0.0.1), e duas camadas decidindo em quem confiar é
# como se erra a identificação do cliente no rate limit.
# --timeout-graceful-shutdown: dá tempo de as etapas em segundo plano
# terminarem antes de o processo cair.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers --timeout-graceful-shutdown 60"]
