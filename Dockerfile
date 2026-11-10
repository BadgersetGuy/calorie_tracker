FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip==26.3
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py mobile_api.py analysis_engine.py meal_timing.py meal_suggestions.py records_api.py photo_inputs.py photo_maintenance.py media_previews.py api_contract.py mcp_bridge.py ./
COPY templates ./templates
EXPOSE 8080
CMD ["sh", "-c", "exec gunicorn --bind \"0.0.0.0:${PORT:-8080}\" --workers 2 --timeout 150 app:app"]
