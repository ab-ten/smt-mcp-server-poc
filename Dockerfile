FROM python:3.12-slim

RUN useradd -m -u 10001 mcp

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY bin/tunnel-client /usr/local/bin/tunnel-client
RUN chmod +x /usr/local/bin/tunnel-client ;\
    install -d -o mcp -m 750 "$HOME/.config"

#COPY server.py /app/server.py
#COPY entrypoint.sh /app/entrypoint.sh
#RUN chmod +x /app/entrypoint.sh && chown -R mcp:mcp /app

USER mcp

ENV MCP_ROOT=/workspace

ENTRYPOINT ["/bin/sh", "-c", "/app/entrypoint.sh"]
