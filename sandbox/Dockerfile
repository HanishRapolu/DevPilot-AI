FROM python:3.12-slim
RUN pip install --no-cache-dir pytest==9.1.1
COPY runner.py /opt/devpilot_runner.py
COPY pytest.ini /opt/pytest.ini
WORKDIR /workspace
USER 65534:65534
ENTRYPOINT ["python", "-I", "/opt/devpilot_runner.py"]
