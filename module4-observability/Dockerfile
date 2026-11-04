FROM python:3.11-slim

WORKDIR /app

# Unicode fonts for PDF exports (accented letters, plus Chinese characters in names).
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core fonts-wqy-microhei \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY .streamlit ./.streamlit
COPY app ./app
COPY tests ./tests

EXPOSE 8501

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=3)"

CMD ["streamlit", "run", "app/main.py"]
