# 口播雷达 MVP Docker 镜像
FROM node:24-bookworm-slim AS pi-deps
WORKDIR /pi-agent
COPY pi-agent/package.json pi-agent/package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts

FROM python:3.11-slim

# lxml/trafilatura 运行时需要的共享库（wheel 已 bundle，装上作保险）
# tzdata 让日志时间用本地时区
RUN apt-get update && apt-get install -y --no-install-recommends \
        libxml2 \
        libxslt1.1 \
        zlib1g \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖，利用 docker 层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安装 Playwright Chromium 及其系统依赖，用于 SPA 站点（如机器之心）JS 渲染抓取
# install-deps 用 apt 装 Chromium 运行所需的共享库；install 下载 Chromium 二进制
# RUN playwright install-deps chromium \
#     && playwright install chromium \
#     && rm -rf /var/lib/apt/lists/*

# 再复制项目代码
COPY app.py config.py ./
COPY migrations/ ./migrations/
COPY repositories/ ./repositories/
COPY services/ ./services/
COPY workers/ ./workers/
COPY prompts/ ./prompts/
COPY templates/ ./templates/
COPY static/ ./static/
COPY --from=pi-deps /usr/local/bin/node /usr/local/bin/node
COPY --from=pi-deps /pi-agent/node_modules ./pi-agent/node_modules/
COPY pi-agent/chat.mjs ./pi-agent/

# 数据库存放目录（用卷挂载持久化）
RUN mkdir -p data
VOLUME ["/app/data"]

# 容器内必须监听 0.0.0.0 才能被外部访问
ENV APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1

# 把时区链接到 /etc/localtime，确保 Python logging / datetime 默认使用 Asia/Shanghai
RUN ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone

EXPOSE 8000

CMD ["python", "app.py"]
