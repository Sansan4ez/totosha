FROM pgvector/pgvector:pg17

RUN localedef -i ru_RU -c -f UTF-8 -A /usr/share/locale/locale.alias ru_RU.UTF-8

ENV LANG=ru_RU.UTF-8
ENV LC_ALL=ru_RU.UTF-8

COPY docker-entrypoint-wrapper.sh /usr/local/bin/docker-entrypoint-wrapper.sh
COPY initdb/10-bootstrap.sh /docker-entrypoint-initdb.d/10-bootstrap.sh
COPY init.sql /docker-entrypoint-initdb.d/20-init.sql.tmpl
COPY series_catalog.json /docker-entrypoint-initdb.d/series_catalog.json
COPY sql/catalog_series_families_seed.sql /docker-entrypoint-initdb.d/24-catalog-series-families-seed.sql
COPY sql/catalog_lamps_agent.sql /docker-entrypoint-initdb.d/25-catalog-lamps-agent.sql
COPY sql/corp_hybrid_search.sql /docker-entrypoint-initdb.d/30-corp-hybrid-search.sql

RUN chmod 755 /usr/local/bin/docker-entrypoint-wrapper.sh /docker-entrypoint-initdb.d/10-bootstrap.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint-wrapper.sh"]
CMD ["postgres"]
