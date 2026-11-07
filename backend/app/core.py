import hashlib
import ipaddress
import re
from urllib.parse import quote, urlsplit

import idna

CODE_BITS = 40
SEGMENT_MAX_LENGTH = 64
DESTINATION_MAX_LENGTH = 250
ROUTE_NAMES = {'api', 'docs', 'redoc', 'health', 'openapi.json'}

_UNSAFE_ESCAPE = re.compile(r'%(?![0-9a-f]{2})|%(?:0[0-9a-f]|1[0-9a-f]|7f)', re.I)
_DNS_LABEL = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?')
_NUMERIC_LABEL = re.compile(r'[0-9]+|0x[0-9a-f]*')
_SEGMENT = re.compile(r'[A-Za-z0-9_-]+')
_PATH_SAFE = "/%:@!$&'()*+,;=-._~"
_QUERY_SAFE = _PATH_SAFE + '?'


def csv_values(value):
    return {item.strip() for item in value.split(',') if item.strip()}


def _has_unsafe_characters(value):
    return any(char.isspace() or ord(char) < 32 or 127 <= ord(char) <= 159 or char == '\\'
               for char in value)


def _dns_name(value):
    return idna.encode(value, uts46=True).decode('ascii').removesuffix('.')


def blocked_destination_hosts(cfg):
    blocked = set()
    for value in csv_values(cfg.blocked_hosts) | csv_values(cfg.blocked_host_suffixes):
        name = value.strip('.')
        if ':' in name:
            blocked.add(str(ipaddress.IPv6Address(name.removeprefix('[').removesuffix(']'))))
        else:
            blocked.add(_dns_name(name))
    return blocked


def _host_and_port(url):
    if url.scheme.lower() != 'https' or not url.hostname or '@' in url.netloc or '%' in url.hostname:
        raise ValueError('URL inválida.')
    bracketed = url.netloc.startswith('[')
    authority = url.netloc.partition(']')[2] if bracketed else url.netloc
    if (bracketed and authority and not authority.startswith(':')) or authority.endswith(':'):
        raise ValueError('URL inválida.')

    if bracketed:
        host = url.hostname.lower()
        address = ipaddress.IPv6Address(host)
    else:
        host = _dns_name(url.hostname)
        try:
            address = ipaddress.IPv4Address(host)
        except ipaddress.AddressValueError:
            address = None
            labels = host.split('.')
            if (len(host) > 253 or len(labels) < 2 or _NUMERIC_LABEL.fullmatch(labels[-1])
                    or any(not _DNS_LABEL.fullmatch(label) for label in labels)):
                raise ValueError('URL inválida.')
    return host, url.port, address


def validate_origin(value):
    if _has_unsafe_characters(value) or '?' in value or '#' in value:
        raise ValueError('Origens públicas devem ser URLs HTTPS válidas')
    try:
        url = urlsplit(value)
        _, port, _ = _host_and_port(url)
        if url.path not in ('', '/') or port == 0:
            raise ValueError()
    except ValueError as exc:
        raise ValueError('Origens públicas devem ser URLs HTTPS válidas') from exc


def _public_address(address):
    if isinstance(address, ipaddress.IPv6Address):
        if address.is_site_local:
            return False
        address = address.ipv4_mapped or address
    return address.is_global and not address.is_multicast and not address.is_reserved


def normalize_url(value, cfg):
    max_length_message = f'A URL deve ter no máximo {cfg.destination_max_length} caracteres.'
    if len(value) > cfg.destination_max_length:
        raise ValueError(max_length_message)
    if _has_unsafe_characters(value) or _UNSAFE_ESCAPE.search(value):
        raise ValueError('URL inválida.')

    try:
        url = urlsplit(value)
        host, port, address = _host_and_port(url)
    except ValueError as exc:
        raise ValueError('URL inválida.') from exc
    if address is not None and not _public_address(address):
        raise ValueError('URL inválida.')
    if port is not None and port not in {int(p) for p in csv_values(cfg.allowed_https_ports)}:
        raise ValueError('URL inválida.')

    blocked = blocked_destination_hosts(cfg)
    for origin in (cfg.short_base_url, cfg.frontend_base_url):
        own_host, _, own_address = _host_and_port(urlsplit(origin))
        if address is not None and address == own_address:
            raise ValueError('URL inválida.')
        blocked.add(own_host)
    canonical_host = str(address) if address is not None else host
    if any(canonical_host == name or canonical_host.endswith('.' + name) for name in blocked):
        raise ValueError('URL inválida.')

    authority = f'[{host}]' if isinstance(address, ipaddress.IPv6Address) else host
    if port is not None:
        authority += f':{port}'
    result = url._replace(
        scheme='https', netloc=authority, path=quote(url.path, safe=_PATH_SAFE),
        query=quote(url.query, safe=_QUERY_SAFE), fragment=quote(url.fragment, safe=_QUERY_SAFE),
    ).geturl()
    if len(result) > cfg.destination_max_length:
        raise ValueError(max_length_message)
    return result


def validate_name(value, cfg, path=False):
    maximum = cfg.public_path_max_length if path else cfg.custom_name_max_length
    minimum = 1 if path else cfg.custom_name_min_length
    reserved = ROUTE_NAMES | {name.lower() for name in csv_values(cfg.reserved_route_names)}
    if not minimum <= len(value) <= maximum or not _SEGMENT.fullmatch(value) or value.lower() in reserved:
        raise ValueError('Nome inválido ou reservado.')
    return value


def is_link_code(code):
    return len(code) <= SEGMENT_MAX_LENGTH and _SEGMENT.fullmatch(code) is not None


def validate_project_name(value):
    name = value.strip()
    if (not name or len(name) > SEGMENT_MAX_LENGTH
            or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in name)):
        raise ValueError('Nome de pasta inválido')
    return name


def generate_code(number, cfg):
    if not 0 < number < 2**CODE_BITS:
        raise ValueError('Sequência esgotada')
    half_bits = CODE_BITS // 2
    mask = (1 << half_bits) - 1
    left, right = number >> half_bits, number & mask
    key = bytes.fromhex(cfg.short_code_key)
    for round_number in range(cfg.feistel_rounds):
        digest = hashlib.blake2b(
            bytes([round_number]) + right.to_bytes(3, 'big'),
            key=key, digest_size=8, person=b'url-v1',
        ).digest()
        left, right = right, left ^ (int.from_bytes(digest, 'big') & mask)

    number = (left << half_bits) | right
    result = ''
    while number:
        number, remainder = divmod(number, 62)
        result = cfg.alphabet[remainder] + result
    return result.rjust(cfg.short_code_length, cfg.alphabet[0])
