# 自建 MinIO 镜像
# 原因：Docker Hub 无法直连，且 minio/minio 在多个国内加速源上均不可用；
#       MinIO 官方已停止 dl.min.io 的二进制分发（返回 410），
#       故使用国内镜像站 dl.minio.org.cn 的 linux-amd64 二进制 + alpine 构建。
# 升级方式：重新下载同目录下的 minio / mc 二进制后 rebuild。
FROM alpine:3.20

RUN apk add --no-cache ca-certificates curl tzdata \
    && cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone

COPY minio /usr/local/bin/minio
COPY mc /usr/local/bin/mc
RUN chmod +x /usr/local/bin/minio /usr/local/bin/mc

EXPOSE 9000 9001

ENTRYPOINT ["minio"]
CMD ["server", "/data", "--console-address", ":9001"]
