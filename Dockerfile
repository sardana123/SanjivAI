FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 SANJEEVANI_HOST=0.0.0.0 SANJEEVANI_DB=/data/sanjeevani.db
WORKDIR /app
COPY pyproject.toml README.md ./
COPY sanjeevani ./sanjeevani
RUN pip install --no-cache-dir . && useradd -m app && mkdir /data && chown app /data
USER app
VOLUME /data
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request as u;u.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["sanjeevani", "serve"]
