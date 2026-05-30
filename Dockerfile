FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Preprocess raw EDGAR .htm filings → clean .txt files in data_room/
# Runs at build time so the correct-sized files are always baked into the image.
RUN python3 preprocess.py

EXPOSE 8501

# API keys injected at runtime via -e flags (Decision 3.13)
# docker run -e ANTHROPIC_API_KEY=... -e GOOGLE_API_KEY=... -p 80:8501 prismforge-ai:latest
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
