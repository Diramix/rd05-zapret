import ctypes
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('cc'), 'Linux C compiler required')
class RawFakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.library_path = Path(cls.directory.name) / 'raw_fake.so'
        subprocess.run([
            'cc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
            str(BASE / 'tools/tpws/raw_fake.c'), '-o', str(cls.library_path),
        ], check=True)
        cls.library = ctypes.CDLL(str(cls.library_path), use_errno=True)
        cls.library.raw_fake_sni_load.argtypes = [ctypes.c_char_p]
        cls.library.raw_fake_sni_load.restype = ctypes.c_bool
        cls.library.raw_fake_sni_reload.restype = ctypes.c_bool
        cls.library.raw_fake_payload.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t)]
        cls.library.raw_fake_payload.restype = ctypes.c_bool
        cls.original = (BASE / 'router/clienthello.bin').read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def load(self, text):
        path = Path(self.directory.name) / 'sni.txt'
        path.write_text(text)
        return self.library.raw_fake_sni_load(str(path).encode())

    def prepare(self, payload=None, capacity=1200):
        data = self.original if payload is None else payload
        source = ctypes.create_string_buffer(data)
        output = ctypes.create_string_buffer(capacity)
        size = ctypes.c_size_t(capacity)
        valid = self.library.raw_fake_payload(source, len(data), output, ctypes.byref(size))
        self.assertEqual(source.raw[:len(data)], data)
        return valid, output.raw[:size.value]

    def hostname(self, data):
        self.assertEqual(int.from_bytes(data[3:5], 'big'), len(data) - 5)
        self.assertEqual(int.from_bytes(data[6:9], 'big'), len(data) - 9)
        position = 44 + data[43]
        position += 2 + int.from_bytes(data[position:position + 2], 'big')
        position += 1 + data[position]
        self.assertEqual(int.from_bytes(data[position:position + 2], 'big'), len(data) - position - 2)
        position += 2
        while position < len(data):
            kind = int.from_bytes(data[position:position + 2], 'big')
            length = int.from_bytes(data[position + 2:position + 4], 'big')
            self.assertLessEqual(position + 4 + length, len(data))
            if kind == 0:
                self.assertEqual(int.from_bytes(data[position + 4:position + 6], 'big'), length - 2)
                self.assertEqual(data[position + 6], 0)
                self.assertEqual(int.from_bytes(data[position + 7:position + 9], 'big'), length - 5)
                return data[position + 9:position + 4 + length].decode('ascii')
            position += 4 + length
        self.fail('SNI extension missing')

    def test_random_names_preserve_tls_lengths_and_original(self):
        names = {'vk.com', 'yandex.ru', 'www.google.com'}
        self.assertTrue(self.load('\n'.join(names)))
        observed = set()
        for _ in range(128):
            valid, data = self.prepare()
            self.assertTrue(valid)
            observed.add(self.hostname(data))
        self.assertEqual(observed, names)

    def test_long_domain_and_output_capacity(self):
        name = '.'.join(['a' * 63] * 3 + ['b' * 61])
        self.assertTrue(self.load(name))
        valid, data = self.prepare()
        self.assertTrue(valid)
        self.assertEqual(self.hostname(data), name)
        self.assertFalse(self.prepare(capacity=len(self.original))[0])

    def test_invalid_reload_keeps_previous_list(self):
        self.assertTrue(self.load('vk.com\n'))
        (Path(self.directory.name) / 'sni.txt').write_text('invalid domain\n')
        self.assertFalse(self.library.raw_fake_sni_reload())
        self.assertEqual(self.hostname(self.prepare()[1]), 'vk.com')

    def test_invalid_names_and_empty_lists_are_rejected(self):
        for name in ['', '# empty\n', '.example.com', 'a..com', '-a.com', 'a-.com', 'a' * 64 + '.com', 'https://vk.com']:
            with self.subTest(name=name):
                self.assertFalse(self.load(name))

    def test_comments_and_crlf_are_supported(self):
        self.assertTrue(self.load(' # ignored\r\n vk.com \t# selected\r\n'))
        self.assertEqual(self.hostname(self.prepare()[1]), 'vk.com')

    def test_truncated_clienthello_is_rejected(self):
        self.assertTrue(self.load('vk.com'))
        for length in range(len(self.original)):
            with self.subTest(length=length):
                self.assertFalse(self.prepare(self.original[:length])[0])
