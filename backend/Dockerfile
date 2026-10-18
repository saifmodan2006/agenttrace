FROM python:3.12-slim
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app app
COPY demo /app/demo
RUN useradd --create-home agenttrace && mkdir /app/.runtime && chown -R agenttrace:agenttrace /app
USER agenttrace
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
