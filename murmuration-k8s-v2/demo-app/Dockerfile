FROM python:3.11-slim
WORKDIR /app
RUN apt-get update -qq && apt-get install -y -qq wget 2>/dev/null || true
COPY app.py .
EXPOSE 8080
CMD ["python", "app.py"]
