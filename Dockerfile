FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 runner \
    && useradd --uid 10001 --gid 10001 --no-create-home runner
COPY --chown=10001:10001 alert_rlvr /app/alert_rlvr
COPY --chown=10001:10001 examples /app/examples
COPY --chown=10001:10001 tests /app/tests
ENV PYTHONPATH=/app
USER 10001:10001
CMD ["python", "-m", "examples.demo"]
