import logging
import re
import uuid
from datetime import datetime, timezone

from ..core import csv_values

_LOG = logging.getLogger('shortener')
_CREDENTIAL_HEADER = re.compile(r'authorization|cookie|token|secret|credential|password|api[-_]?key', re.I)


class AccessRecorder:
    def __init__(self, save, extra_headers: str, extra_pattern: str, marker: str):
        self.save = save
        self.extra_headers = {header.lower() for header in csv_values(extra_headers)}
        try:
            self.extra_pattern = re.compile(extra_pattern, re.I) if extra_pattern else None
        except re.error as exc:
            raise ValueError('ANALYTICS_REDACTED_HEADER_PATTERN inválido') from exc
        self.marker = marker

    def _redact(self, headers):
        redacted = []
        for raw_name, raw_value in headers:
            name = raw_name.decode('latin1')
            protected = (
                name.lower() in self.extra_headers or _CREDENTIAL_HEADER.search(name)
                or (self.extra_pattern is not None and self.extra_pattern.search(name))
            )
            redacted.append([name, self.marker if protected else raw_value.decode('latin1')])
        return redacted

    def __call__(self, code, path, method, status, found, headers):
        try:
            payload = {
                'event_id': str(uuid.uuid4()),
                'schema_version': 1,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'short_code': code if found else None,
                'requested_code': code,
                'requested_path': path,
                'method': method,
                'status': status,
                'headers': self._redact(headers),
            }
            self.save(payload)
        except Exception:
            _LOG.warning('Evento de acesso não foi gravado')
