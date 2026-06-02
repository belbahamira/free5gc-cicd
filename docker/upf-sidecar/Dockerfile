FROM python:3.11-slim
RUN pip install prometheus-client
COPY sidecar.py /app/sidecar.py
CMD ["python3", "/app/sidecar.py"]
