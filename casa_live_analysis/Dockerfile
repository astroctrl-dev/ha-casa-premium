ARG BUILD_FROM=python:3.12-alpine
FROM ${BUILD_FROM}
RUN pip install --no-cache-dir aiohttp==3.11.13
WORKDIR /app
COPY server.py /app/server.py
COPY index.html /app/index.html
EXPOSE 8099
CMD ["python3","/app/server.py"]
