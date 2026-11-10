FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
COPY requirements-app.txt requirements-ml.txt /app/
RUN pip install --no-cache-dir -r requirements-ml.txt
COPY ml/ /app/ml/
COPY data/ /app/data/
CMD ["python","ml/train.py"]
