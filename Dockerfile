# Stage 1: 构建前端
FROM node:20-alpine AS frontend-builder
RUN corepack enable
WORKDIR /app/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

# Stage 2: Python 后端 + 前端静态文件
FROM python:3.11-slim
WORKDIR /app

# 安装依赖
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码
COPY backend/ ./

# 复制前端构建产物
COPY --from=frontend-builder /app/frontend/dist ./static

# 创建数据目录（运行时通过 volume 挂载覆盖）
RUN mkdir -p data/logs

EXPOSE 8000
CMD ["python", "main.py"]
