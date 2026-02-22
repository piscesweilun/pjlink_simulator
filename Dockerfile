FROM python:3.9-slim
WORKDIR /app
COPY pjlink_simulator.py .
# 在下方這行加上 /app/ 的絕對路徑
CMD ["python", "-u", "/app/pjlink_simulator.py"]