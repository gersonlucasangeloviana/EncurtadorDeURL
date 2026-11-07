FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY app ./app
COPY tests /tests
ENV PYTHONPATH=/app
CMD ["sh", "-c", "python -W error::RuntimeWarning -m unittest discover -s /tests -v && python -W error::RuntimeWarning -m unittest discover -s /tests/integration -v"]
