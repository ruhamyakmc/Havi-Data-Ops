FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    cron \
    procps \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /usr/sbin/nologin havi

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY entrypoint.sh /entrypoint.sh
# COPY preserves host file modes verbatim, which are often owner-only (600/700)
# on developer machines. Normalize so the non-root `havi` cron user can read
# the app source regardless of what the permissions happened to be on disk.
RUN chmod -R a+rX /app \
    && chmod +x /entrypoint.sh \
    && mkdir -p /var/log/havi /app/Downloads /app/Extracted \
    && chown -R havi:havi /var/log/havi /app/Downloads /app/Extracted

ENTRYPOINT ["/entrypoint.sh"]
