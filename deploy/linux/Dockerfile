# 码章鲸常驻存稿服务：固定依赖、非 root、单可写卷，不含浏览器。
# 基础镜像按 tag 而非 digest 锁定；离线环境请先把镜像同步到私有仓库再改成本地 digest。
# 多架构：`docker buildx build --platform linux/amd64` 或 `--platform linux/arm64`。
# buildx 会按目标平台拉取同架构的 python 基础镜像；arm64 产物仍需在真实 aarch64 主机验收。
FROM docker.io/library/python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONUTF8=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    NOVEL_HELPER_ROOT=/data \
    TZ=Asia/Shanghai

# 固定依赖：服务本体只用标准库；tzdata 让 zoneinfo 在 slim 镜像里可用。
# 离线构建时把该文件换成本地 wheel 目录：COPY wheels/ /wheels/ && pip install --no-index --find-links=/wheels ...
COPY deploy/linux/requirements-linux.txt /tmp/requirements-linux.txt
RUN pip install --no-cache-dir --only-binary :all: -r /tmp/requirements-linux.txt \
    && rm -f /tmp/requirements-linux.txt

# 非 root 用户；数据卷只由它写入。
RUN groupadd --gid 10001 whale \
    && useradd --uid 10001 --gid 10001 --home-dir /data --no-create-home --shell /usr/sbin/nologin whale \
    && mkdir -p /data /app /config \
    && chown -R 10001:10001 /data /app

WORKDIR /app
COPY backend/ /app/backend/
COPY deploy/linux/entrypoint.sh /app/entrypoint.sh
RUN chmod 0755 /app/entrypoint.sh && chown -R 10001:10001 /app

USER 10001:10001
# 服务不监听端口；必须把 /data 挂到宿主卷，否则数据落在匿名卷里。
VOLUME ["/data"]
STOPSIGNAL SIGTERM
ENV PYTHONPATH=/app/backend

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
  CMD ["python", "-B", "-X", "utf8", "-m", "integration.resident_service", "health"]

ENTRYPOINT ["/app/entrypoint.sh"]
