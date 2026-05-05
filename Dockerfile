FROM python:3.12-slim

WORKDIR /app

COPY server.py /app/server.py
COPY public /app/public

ENV HOST=0.0.0.0
ENV PORT=8088
ENV REVENUE_DATA_DIR=/app/data
ENV PYTHONUNBUFFERED=1

EXPOSE 8088

CMD ["python", "server.py"]
