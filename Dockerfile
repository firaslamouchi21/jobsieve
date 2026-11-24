FROM mcr.microsoft.com/playwright/python:v1.54.0-jammy
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir ".[all]"
RUN chmod +x /app/start_combined.sh
EXPOSE 8000 8501
CMD ["/app/start_combined.sh"]
