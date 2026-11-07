import hashlib
import json
import math
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from .core import (
    CODE_BITS, DESTINATION_MAX_LENGTH, SEGMENT_MAX_LENGTH,
    blocked_destination_hosts, csv_values, validate_origin,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    short_base_url: str = 'https://urlbase.example'
    frontend_base_url: str = 'https://painel.urlbase.example'
    allowed_hosts: str = 'urlbase.example,painel.urlbase.example'
    database_url: str = 'postgresql+psycopg://shortener:change@postgres/shortener'
    redis_url: str = 'redis://redis:6379/0'
    redis_cache_ttl_seconds: int = 1800
    redis_fill_ttl_seconds: int = 5
    redis_socket_timeout_seconds: float = 0.02
    cache_key_prefix: str = 'shortener'
    destination_max_length: int = DESTINATION_MAX_LENGTH
    allowed_https_ports: str = '443'
    blocked_hosts: str = 'localhost,postgres,redis'
    blocked_host_suffixes: str = '.localhost,.local,.internal'
    custom_name_min_length: int = 3
    custom_name_max_length: int = SEGMENT_MAX_LENGTH
    public_path_max_length: int = SEGMENT_MAX_LENGTH
    reserved_route_names: str = 'auth,assets,admin'
    short_code_key: str = ''
    short_code_bits: int = CODE_BITS
    feistel_rounds: int = 8
    alphabet: str = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
    short_code_length: int = 7
    short_code_generation_max_attempts: int = 10
    short_code_algorithm_version: int = 1
    api_key: str = ''
    admin_password: str = ''
    analytics_redacted_headers: str = ''
    analytics_redacted_header_pattern: str = ''
    analytics_redaction_marker: str = '[REDACTED]'
    analytics_max_events: int = 100_000

    def check(self):
        for origin in (self.short_base_url, self.frontend_base_url):
            validate_origin(origin)
        blocked_destination_hosts(self)
        if not csv_values(self.allowed_hosts):
            raise ValueError('Configure ALLOWED_HOSTS')
        ports = csv_values(self.allowed_https_ports)
        if not ports or any(not p.isascii() or not p.isdecimal() or not 1 <= int(p) <= 65535 for p in ports):
            raise ValueError('ALLOWED_HTTPS_PORTS deve conter portas entre 1 e 65535')
        try:
            key = bytes.fromhex(self.short_code_key)
        except ValueError as exc:
            raise ValueError('SHORT_CODE_KEY must be hexadecimal') from exc
        if len(key) != 32:
            raise ValueError('Configure SHORT_CODE_KEY')
        if (
            self.short_code_bits != CODE_BITS
            or self.short_code_algorithm_version != 1
            or not 4 <= self.feistel_rounds <= 32
            or len(self.alphabet) != 62
            or len(set(self.alphabet)) != 62
            or not self.alphabet.isascii()
            or not self.alphabet.isalnum()
            or not 1 <= self.short_code_length <= SEGMENT_MAX_LENGTH
            or 62**self.short_code_length < 2**CODE_BITS
        ):
            raise ValueError('Invalid short code algorithm configuration')
        if not (
            1 <= self.destination_max_length <= DESTINATION_MAX_LENGTH
            and 1 <= self.custom_name_min_length <= self.custom_name_max_length <= SEGMENT_MAX_LENGTH
            and 1 <= self.public_path_max_length <= SEGMENT_MAX_LENGTH
            and self.redis_cache_ttl_seconds > 0
            and self.redis_fill_ttl_seconds > 0
            and math.isfinite(self.redis_socket_timeout_seconds)
            and self.redis_socket_timeout_seconds > 0
            and self.short_code_generation_max_attempts > 0
            and 1 <= self.analytics_max_events < 2**63
        ):
            raise ValueError('Invalid application limits')
        if len(self.api_key) != 64 or any(c not in '0123456789abcdef' for c in self.api_key):
            raise ValueError('API_KEY must be 32 random bytes in lowercase hexadecimal')
        if not 16 <= len(self.admin_password) <= 128 or any(not 33 <= ord(c) <= 126 for c in self.admin_password):
            raise ValueError('ADMIN_PASSWORD must contain 16 to 128 visible ASCII characters')
        return self

    def fingerprint(self):
        data = [
            self.short_code_key, self.short_code_bits, self.feistel_rounds,
            self.alphabet, self.short_code_length, self.short_code_algorithm_version,
        ]
        return hashlib.sha256(json.dumps(data).encode()).hexdigest()


@lru_cache
def settings():
    return Settings().check()
