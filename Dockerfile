FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py storage.py auth.py scoring.py adjudicator.py katago.cfg rules_policy.py preview_bot.py ./
COPY index.html ./static/index.html
ENV PORT=8080
EXPOSE 8080
CMD ["python", "server.py"]
