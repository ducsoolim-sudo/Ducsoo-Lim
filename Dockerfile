FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
ARG GO13_PREVIEW=false
COPY build_preview_engine.py ./
RUN if [ "$GO13_PREVIEW" = "true" ]; then python build_preview_engine.py; fi
COPY server.py storage.py auth.py scoring.py adjudicator.py katago.cfg rules_policy.py preview_bot.py strong_bot.py ./
COPY index.html ./static/index.html
COPY stone-placement.wav brand-intro.wav ./static/
ENV PORT=8080
EXPOSE 8080
CMD ["python", "server.py"]
