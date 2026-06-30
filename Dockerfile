# AI Agent Efficiency Coach MVP Docker 镜像
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

# 再复制项目代码
COPY app.py config.py ./
COPY migrations/ ./migrations/
COPY repositories/ ./repositories/
COPY services/ ./services/
COPY workers/ ./workers/
COPY prompts/ ./prompts/
COPY templates/ ./templates/
COPY static/ ./static/

# 数据库存放目录（用卷挂载持久化）
RUN mkdir -p data
VOLUME ["/app/data"]

# 容器内必须监听 0.0.0.0 才能被外部访问
ENV APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["python", "app.py"]
