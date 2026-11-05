from contextlib import redirect_stdout
import io
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from scripts.check_messages import Client, ReadError, conversations, inspect, matches


class MessageReadTests(unittest.TestCase):
    def test_hosts_and_optional_version(self):
        self.assertEqual(Client('secret', 'unified', '').base, 'https://graph.facebook.com')
        self.assertEqual(Client('secret', 'instagram', 'v99.0').base, 'https://graph.instagram.com/v99.0')

    def test_match_uses_id_or_username_not_display_name(self):
        self.assertTrue(matches({'id': '123'}, '123'))
        self.assertTrue(matches({'username': 'Example'}, '@example'))
        self.assertFalse(matches({'name': 'example'}, '@example'))

    def test_listing_does_not_read_messages_and_paging_uses_cursor(self):
        client = Mock()
        client.get.side_effect = [
            {'data': [{'id': 'c1', 'participants': {'data': [{'id': '123'}]}}],
             'paging': {'next': 'https://evil.example/?access_token=secret', 'cursors': {'after': 'cursor'}}},
            {'data': []}]
        with redirect_stdout(io.StringIO()):
            inspect(client, '999', None, list_only=True)
        self.assertEqual(client.get.call_count, 2)
        self.assertEqual(client.get.call_args.args, ('999/conversations',))
        self.assertEqual(client.get.call_args.kwargs['after'], 'cursor')

    def test_selected_sender_and_attachment_field_failure(self):
        client = SimpleNamespace(token='secret', get=Mock())
        client.get.side_effect = [
            {'data': [{'id': 'c1', 'participants': {'data': [{'id': '123', 'username': 'example'}]}},
                      {'id': 'c2', 'participants': {'data': [{'id': '456'}]}}]},
            {'messages': {'data': [{'id': 'm1'}, {'id': 'm2'}]}},
            {'id': 'm1', 'from': {'id': '123'}, 'message': 'hola'},
            ReadError('Campo no soportado'),
            {'shares': {'data': [{'link': 'https://www.instagram.com/reel/ABC/'}]}},
            {'id': 'm2', 'from': {'id': '999'}, 'message': 'respuesta privada'},
        ]
        output = io.StringIO()
        with redirect_stdout(output):
            count = inspect(client, '999', '@example')
        self.assertEqual(count, 1)
        self.assertIn('attachments_diagnostic', output.getvalue())
        self.assertIn('/reel/ABC/', output.getvalue())
        self.assertNotIn('respuesta privada', output.getvalue())
        self.assertEqual(client.get.call_count, 6)


if __name__ == '__main__':
    unittest.main()
