FROM node:22-bookworm AS web
WORKDIR /src/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY apps/api ./apps/api
COPY packages ./packages
RUN pip install --no-cache-dir -e .
COPY --from=web /src/apps/web/dist ./apps/web/dist
ENV PORT=8000
ENV REVIEWDESK_RUNS_DIR=/tmp/reviewdesk-runs
EXPOSE 8000
CMD ["sh", "-c", "uvicorn reviewdesk_api.main:app --host 0.0.0.0 --port ${PORT}"]
