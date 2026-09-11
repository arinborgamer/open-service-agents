FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY open_service_agents ./open_service_agents
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home osa && mkdir /data && chown osa /data
USER osa
EXPOSE 8787
ENTRYPOINT ["osa", "--data", "/data"]
CMD ["serve", "--host", "0.0.0.0"]
