FROM pgvector/pgvector:pg17

RUN localedef -i ru_RU -c -f UTF-8 -A /usr/share/locale/locale.alias ru_RU.UTF-8

ENV LANG=ru_RU.UTF-8
ENV LC_ALL=ru_RU.UTF-8

COPY docker-entrypoint-wrapper.sh /usr/local/bin/docker-entrypoint-wrapper.sh
COPY initdb/10-bootstrap.sh /docker-entrypoint-initdb.d/10-bootstrap.sh
COPY init.sql /docker-entrypoint-initdb.d/20-init.sql.tmpl

RUN chmod 755 /usr/local/bin/docker-entrypoint-wrapper.sh /docker-entrypoint-initdb.d/10-bootstrap.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint-wrapper.sh"]
CMD ["postgres"]
