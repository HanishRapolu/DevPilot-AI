FROM python:3.12-slim
RUN pip install --no-cache-dir pytest==9.1.1
WORKDIR /workspace
COPY calculator.py test_calculator.py pytest.ini ./
USER 65534:65534
CMD ["python", "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
