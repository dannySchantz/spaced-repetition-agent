FROM python:3.12.13-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 RECALL_DB=/data/recall.db
WORKDIR /app
COPY requirements.lock pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps . \
    && useradd --uid 10001 --create-home recall && mkdir /data && chown recall:recall /data
USER recall
EXPOSE 8765
CMD ["recall", "serve", "--host", "0.0.0.0", "--port", "8765"]
