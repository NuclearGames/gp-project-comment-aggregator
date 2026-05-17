FROM python:3.12-slim

WORKDIR /app

COPY bot/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ ./bot/
COPY shared/ ./shared/

ENV PYTHONPATH=/app

CMD ["python", "bot/bot.py"]
