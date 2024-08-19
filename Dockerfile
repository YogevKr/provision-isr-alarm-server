FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alarm_server.py .

CMD ["python", "alarm_server.py"]
