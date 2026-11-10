FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
COPY requirements-app.txt /app/
RUN pip install --no-cache-dir -r requirements-app.txt
COPY shared/ /app/shared/
COPY services/ /app/services/
COPY scripts/demo_reentrega.py /app/scripts/demo_reentrega.py
CMD ["uvicorn","services.products.app:app","--host","0.0.0.0","--port","8000"]
