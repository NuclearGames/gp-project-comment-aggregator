FROM python:3.12-slim

WORKDIR /app

COPY worker/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY worker/ ./worker/
COPY shared/ ./shared/

ENV PYTHONPATH=/app

CMD ["python", "worker/main.py"]
