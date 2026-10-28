"""Offline tests for the text Formatted Zone."""

import importlib.util
import io
import json
import unittest
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'formatted_zone/format_text.py'
spec = importlib.util.spec_from_file_location('format_text', SCRIPT)
ft = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ft)


def as_json(document):
    return json.dumps(document, ensure_ascii=False).encode('utf-8')


class JsonHybridExtractionTests(unittest.TestCase):
    def test_priority_key_is_used_first(self):
        doc = {
            'id': 7,
            'title': 'Iberian lynx',
            'description': 'Endemic felid of the Iberian Peninsula.',
            'notes': 'x' * 500,
        }
        text, details = ft.convert_text(as_json(doc), '.json')
        self.assertEqual(text, 'Endemic felid of the Iberian Peninsula.\n')
        self.assertEqual(details['extraction_method'], 'json_priority_key')
        self.assertEqual(details['json_path'], '$.description')

    def test_priority_order_breaks_ties_at_same_depth(self):
        _, details = ft.convert_text(as_json({'summary': 'short', 'text': 'main body'}), '.json')
        self.assertEqual(details['json_path'], '$.text')

    def test_shallowest_priority_key_wins(self):
        doc = {'summary': 'Document summary', 'comments': [{'text': 'A user comment'}]}
        _, details = ft.convert_text(as_json(doc), '.json')
        self.assertEqual(details['json_path'], '$.summary')

    def test_nested_priority_key_and_case_insensitive_match(self):
        doc = {'query': {'pages': [{'pageid': 1, 'Extract': 'El lince ibérico es un felino.'}]}}
        text, details = ft.convert_text(as_json(doc), '.json')
        self.assertEqual(text, 'El lince ibérico es un felino.\n')
        self.assertEqual(details['json_path'], '$.query.pages[0].Extract')

    def test_list_of_paragraphs_under_priority_key(self):
        text, _ = ft.convert_text(
            as_json({'content': ['First paragraph.', 'Second paragraph.']}), '.json'
        )
        self.assertEqual(text, 'First paragraph.\n\nSecond paragraph.\n')

    def test_longest_string_fallback_for_unknown_schema(self):
        doc = {
            'species': 'Bubo bubo',
            'meta': {
                'source': 'api',
                'blocks': ['tiny', 'The eagle-owl is the largest owl in Europe.'],
            },
        }
        text, details = ft.convert_text(as_json(doc), '.json')
        self.assertEqual(text, 'The eagle-owl is the largest owl in Europe.\n')
        self.assertEqual(details['extraction_method'], 'json_longest_string')
        self.assertEqual(details['json_path'], '$.meta.blocks[1]')

    def test_html_inside_json_is_converted(self):
        text, details = ft.convert_text(
            as_json({'description': '<p>Habitat: <b>forest</b></p>'}), '.json'
        )
        self.assertEqual(text, 'Habitat: forest\n')
        self.assertEqual(details['extraction_method'], 'json_priority_key+html')

    def test_array_of_records(self):
        doc = [{'id': 1, 'text': 'Record one.'}, {'id': 2, 'text': 'Record two.'}]
        text, details = ft.convert_text(as_json(doc), '.json')
        self.assertEqual(text, 'Record one.\n\nRecord two.\n')
        self.assertEqual(details['json_path'], 'per_record')

    def test_json_lines(self):
        raw = b'{"body": "Line one."}\n\n{"other": "Line two."}\n'
        text, details = ft.convert_text(raw, '.jsonl')
        self.assertEqual(text, 'Line one.\n\nLine two.\n')
        self.assertEqual(details['extraction_method'], 'json_longest_string+json_priority_key')

    def test_json_without_text_is_rejected(self):
        with self.assertRaises(ValueError):
            ft.convert_text(as_json({'id': 1, 'values': [1, 2, 3]}), '.json')


class EncodingAndCanonicalFormTests(unittest.TestCase):
    def test_crlf_bom_nfc_and_trailing_newline(self):
        raw = '\ufeffLince ibe\u0301rico\r\nsegunda li\u0301nea\r\n\r\n\r\n'.encode('utf-8')
        text, details = ft.convert_text(raw, '.txt')
        self.assertEqual(text, 'Lince ibérico\nsegunda línea\n')
        self.assertEqual(details['source_encoding'], 'utf-8-sig')

    def test_utf16_and_legacy_encodings(self):
        text, details = ft.convert_text('Águila real'.encode('utf-16'), '.txt')
        self.assertEqual((text, details['source_encoding']), ('Águila real\n', 'utf-16'))
        text, _ = ft.convert_text('Martín pescador común: un ave pequeña'.encode('cp1252'), '.txt')
        self.assertEqual(text, 'Martín pescador común: un ave pequeña\n')

    def test_plain_text_spacing_is_preserved(self):
        text, _ = ft.convert_text(b'a  b\n\tc', '.txt')
        self.assertEqual(text, 'a  b\n\tc\n')

    def test_control_characters_are_removed(self):
        text, _ = ft.convert_text(b'abc\x00\x07def', '.txt')
        self.assertEqual(text, 'abcdef\n')


class MarkupFormatTests(unittest.TestCase):
    def test_html(self):
        raw = (
            b'<html><head><title>T</title><style>p{}</style></head><body>'
            b'<h1>Lynx</h1><script>alert(1)</script><p>Lives in&nbsp;Spain &amp; Portugal.</p></body></html>'
        )
        text, _ = ft.convert_text(raw, '.html')
        self.assertEqual(text, 'Lynx\n\nLives in Spain & Portugal.\n')

    def test_xml(self):
        text, _ = ft.convert_text(
            b'<species><name>Sus scrofa</name><desc>Wild boar.</desc></species>', '.xml'
        )
        self.assertEqual(text, 'Sus scrofa\nWild boar.\n')

    def test_markdown(self):
        raw = b'# Red deer\n\nThe **red deer** lives in [forests](http://x.org).\n\n- one\n- two\n'
        text, _ = ft.convert_text(raw, '.md')
        self.assertEqual(text, 'Red deer\n\nThe red deer lives in forests.\n\none\ntwo\n')

    def test_markdown_keeps_snake_case(self):
        text, _ = ft.convert_text(b'species_id lynx_pardinus', '.md')
        self.assertEqual(text, 'species_id lynx_pardinus\n')


class BinaryDocumentTests(unittest.TestCase):
    def test_docx(self):
        ns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
        document = (
            f'<w:document xmlns:w="{ns}"><w:body>'
            '<w:p><w:r><w:t>Timon lepidus</w:t></w:r></w:p>'
            '<w:p><w:r><w:t xml:space="preserve">Lagarto </w:t></w:r><w:r><w:t>ocelado</w:t></w:r></w:p>'
            '</w:body></w:document>'
        )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('word/document.xml', document)
        text, details = ft.convert_text(buffer.getvalue(), '.bin')
        self.assertEqual(text, 'Timon lepidus\nLagarto ocelado\n')
        self.assertEqual(details['source_format'], 'docx')

    def test_odt(self):
        ns = 'urn:oasis:names:tc:opendocument:xmlns:text:1.0'
        content = (
            f'<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            f'xmlns:text="{ns}"><office:body><office:text>'
            '<text:h>Rana común</text:h><text:p>Pelophylax perezi</text:p>'
            '</office:text></office:body></office:document-content>'
        )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('content.xml', content)
        text, _ = ft.convert_text(buffer.getvalue(), '.odt')
        self.assertEqual(text, 'Rana común\nPelophylax perezi\n')

    def test_pdf_without_text_layer_is_rejected(self):
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        buffer = io.BytesIO()
        writer.write(buffer)
        with self.assertRaises(ValueError):
            ft.convert_text(buffer.getvalue(), '.pdf')

    def test_unsupported_extension(self):
        with self.assertRaises(ValueError):
            ft.convert_text(b'data', '.xyz')


class KeyAndMetadataTests(unittest.TestCase):
    def test_formatted_key(self):
        key = (
            'persistent_landing/text/lynx_pardinus/gbif$lynx_pardinus$01-10-2026_10-00-00$abc.html'
        )
        self.assertEqual(
            ft.build_formatted_key(key),
            'text/lynx_pardinus/gbif$lynx_pardinus$01-10-2026_10-00-00$abc.txt',
        )

    def test_metadata_is_ascii(self):
        details = {
            'source_format': 'json',
            'source_encoding': 'utf-8',
            'extraction_method': 'json_priority_key',
            'json_path': '$.descripción',
        }
        metadata = ft.build_formatted_metadata(
            'persistent_landing/text/a/b.json',
            {'modality': 'text', 'species_id': 'a', 'source_name': 'gbif'},
            'texto\n',
            details,
        )
        self.assertTrue(all(value.isascii() for value in metadata.values()))
        self.assertEqual(metadata['char_count'], '6')


if __name__ == '__main__':
    unittest.main()
