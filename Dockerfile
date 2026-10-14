FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY creditlens ./creditlens
RUN pip install --no-cache-dir . && useradd --create-home creditlens && chown -R creditlens:creditlens /app
USER creditlens
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "creditlens.api:app", "--host", "0.0.0.0", "--port", "8000"]
