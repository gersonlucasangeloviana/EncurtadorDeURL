import unittest

from app.config import Settings
from app.core import generate_code, normalize_url, validate_name


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Settings(_env_file=None, short_code_key='01' * 32)

    def test_url_normalization(self):
        self.assertEqual(
            normalize_url('HTTPS://EXAMPLE.COM/a?x=1&x=2#part', self.cfg),
            'https://example.com/a?x=1&x=2#part',
        )
        self.assertEqual(normalize_url('https://[2606:4700::1111]/', self.cfg), 'https://[2606:4700::1111]/')

    def test_bad_urls(self):
        for value in (
            'http://example.com', 'https://user@example.com', 'https://127.0.0.1',
            'https://[::1]', 'https://[v1.example]', 'https://[2606:4700::1111]other.com',
            'https://224.0.0.1', 'https://[ff02::1]', 'https://[::ffff:224.0.0.1]',
            'https://example.com/%0dfoo', 'https://example.com/\u00a0',
            'https://example.com:444', 'https://example.com:', 'https://example.com..',
            'https://urlbase.example/a', 'https://0x7f000001',
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_url(value, self.cfg)

    def test_configured_limit_appears_in_error(self):
        cfg = self.cfg.model_copy(update={'destination_max_length': 10})
        with self.assertRaisesRegex(ValueError, '10 caracteres'):
            normalize_url('https://example.com', cfg)

    def test_unicode_hostname_uses_nontransitional_idna(self):
        self.assertEqual(normalize_url('https://faß.de/', self.cfg), 'https://xn--fa-hia.de/')
        cfg = self.cfg.model_copy(update={'blocked_host_suffixes': '.faß.de'})
        with self.assertRaises(ValueError):
            normalize_url('https://sub.xn--fa-hia.de/', cfg)
        self.assertEqual(normalize_url('https://fass.de/', cfg), 'https://fass.de/')

    def test_names(self):
        self.assertEqual(validate_name('MinhaOferta', self.cfg), 'MinhaOferta')
        cfg = self.cfg.model_copy(update={'reserved_route_names': ''})
        for name in ('api', 'redoc', '../admin', 'a b', 'a%2fb'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_name(name, cfg)

    def test_feistel_unique(self):
        codes = {generate_code(number, self.cfg) for number in range(1, 10001)}
        self.assertEqual(len(codes), 10000)
        self.assertTrue(all(len(code) == 7 for code in codes))

    def test_feistel_preserves_version_one_codes(self):
        for number, code in ((1, '5KJB3Iz'), (10000, 'jccz2j5'), (2**40 - 1, 'iDtrBas')):
            with self.subTest(number=number):
                self.assertEqual(generate_code(number, self.cfg), code)
