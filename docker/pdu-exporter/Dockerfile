FROM python:3.9-slim
RUN pip install prometheus_client requests
COPY exporter.py /app/exporter.py
CMD ["python3", "-u", "/app/exporter.py"]
