FROM python:3

COPY . /app
WORKDIR /app

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "-u", "umbrella_event_importer.py"]
