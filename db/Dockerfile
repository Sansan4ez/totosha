FROM pgvector/pgvector:pg17

# Install Russian locale for full-text search
RUN localedef -i ru_RU -c -f UTF-8 -A /usr/share/locale/locale.alias ru_RU.UTF-8

ENV LANG=ru_RU.UTF-8
ENV LC_ALL=ru_RU.UTF-8

# Copy initialization scripts
COPY init.sql /docker-entrypoint-initdb.d/01-init.sql
