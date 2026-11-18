FROM node:22-alpine AS ui
WORKDIR /ui
COPY queue_ui/package.json queue_ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY queue_ui/index.html queue_ui/tsconfig.json queue_ui/vite.config.ts queue_ui/vite.admin.config.ts ./
COPY queue_ui/src ./src
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY task_queue /app/task_queue
COPY --from=ui /ui/dist /app/queue_ui/dist
COPY --from=ui /ui/admin-dist /app/queue_ui/admin-dist
EXPOSE 8767 8771
CMD ["python", "-m", "task_queue.mcp_server"]
