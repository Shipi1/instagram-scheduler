import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.clients import Instagram, RemoteError
from app.config import Config
from app.runner import Runner, parse_message
from app.store import Store
from scripts.prepare_video import prepare_video, probe


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        users = root / 'users.json'
        users.write_text('{"allowed_user_ids":[123,456]}')
        self.config = SimpleNamespace(
            account='999', version='v99.0', caption='Predeterminada', users=users,
            data=root / 'data', public=root / 'public', public_url='https://example.com/media',
            publish=True, cookies='', ig_token='secret-ig', telegram_token='secret-tg')
        self.config.data.mkdir()
        (self.config.data / 'work').mkdir()
        self.config.public.mkdir()
        self.store = Store(self.config.data / 'jobs.sqlite3')
        self.runner = Runner(self.config, self.store, threading.Event())

    def update(self, number=1, user=123, code='ABC', caption='Descripción\n#hola'):
        return {'update_id': number, 'message': {'message_id': number, 'date': 1,
            'from': {'id': user}, 'chat': {'id': user, 'type': 'private'},
            'text': f'https://www.instagram.com/p/{code}/\n\n{caption}'}}

    def job(self):
        return self.store.rows('SELECT * FROM jobs ORDER BY created')[0]

    def test_caption_fallback_and_multiline(self):
        self.assertEqual(parse_message('https://www.instagram.com/reel/ABC/\n ', 'Default')[1], 'Default')
        self.assertEqual(parse_message('https://www.instagram.com/p/ABC/\n\nHola\n#tag', '')[1], 'Hola\n#tag')
        self.assertEqual(parse_message('https://www.instagram.com/p/ABC/', '')[1], '')
        with self.assertRaises(ValueError):
            parse_message('https://example.com/p/ABC/', '')
        with self.assertRaises(ValueError):
            parse_message('https://www.instagram.com/p/ABC/\n' + 'a' * 2201, '')

    def test_offset_and_duplicate_shortcode_survive_reopen(self):
        self.runner.receive(self.update())
        self.runner.receive(self.update())
        self.runner.receive(self.update(number=2, user=456))
        reopened = Store(self.config.data / 'jobs.sqlite3')
        self.assertEqual(len(reopened.rows('SELECT * FROM jobs')), 1)
        self.assertEqual(reopened.offset(), 3)
        self.assertEqual(self.job()['caption'], 'Descripción\n#hola')
        reopened.bind_bot(100)
        reopened.bind_bot(100)
        with self.assertRaises(RuntimeError):
            reopened.bind_bot(200)

    def test_unauthorized_and_invalid_config_fail_closed(self):
        self.runner.receive(self.update(user=777))
        self.assertEqual(len(self.store.rows('SELECT * FROM jobs')), 0)
        self.config.users.write_text('{broken')
        with self.assertRaises(RuntimeError):
            self.runner.receive(self.update(number=2))
        self.assertEqual(self.store.offset(), 2)

    def fake_download(self, job, folder):
        path = folder / 'instagram_ABC.mp4'
        path.write_bytes(b'original')
        return path

    def fake_prepare(self, original):
        ready = original.with_name('instagram_ABC_ready.mp4')
        ready.write_bytes(b'prepared')
        return ready

    def run_pipeline(self):
        self.runner.receive(self.update())
        self.runner.download = self.fake_download
        self.runner.ig = Mock()
        self.runner.ig.call.side_effect = [
            {'id': 'container'}, {'status_code': 'FINISHED'},
            {'id': 'media'}, {'permalink': 'https://www.instagram.com/reel/RESULT/'}]
        with patch('app.runner.prepare_video', side_effect=self.fake_prepare), patch('app.runner.verify_public'):
            self.runner.process(self.job())

    def test_end_to_end_mocked_and_cleanup(self):
        self.run_pipeline()
        job = self.job()
        self.assertEqual(job['status'], 'PUBLISHED')
        self.assertEqual(job['media_id'], 'media')
        self.assertEqual(job['cleanup'], 'DONE')
        self.assertFalse((self.config.data / 'work' / job['id']).exists())
        self.assertFalse((self.config.public / f"{job['id']}_ready.mp4").exists())
        creation = self.runner.ig.call.call_args_list[0]
        self.assertEqual(creation.kwargs['caption'], 'Descripción\n#hola')
        # Otro intento de finalizar nunca envía un POST.
        self.runner.ig.call.reset_mock()
        self.runner.finalize(self.job())
        self.runner.ig.call.assert_not_called()

    def test_prepare_mode_never_posts(self):
        self.config.publish = False
        self.run_pipeline()
        self.assertEqual(self.job()['status'], 'PREPARED')
        self.runner.ig.call.assert_not_called()

    def test_pipeline_logs_stages_and_cleanup_without_caption(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.run_pipeline()
        entries = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([entry['status'] for entry in entries], [
            'QUEUED', 'DOWNLOADING', 'PREPARING', 'HOSTING', 'CREATING_CONTAINER',
            'PROCESSING', 'READY_TO_PUBLISH', 'PUBLISHING', 'PUBLISHED', 'PUBLISHED', 'PUBLISHED'])
        self.assertTrue(all(entry['job_id'] == self.job()['id'] for entry in entries))
        self.assertEqual(entries[-1]['cleanup'], 'DONE')
        self.assertNotIn('Descripción', output.getvalue())
        self.assertNotIn('secret-ig', output.getvalue())

    def test_ambiguous_publication_is_not_retried(self):
        self.runner.receive(self.update())
        job = self.job()
        self.store.change(job['id'], 'PUBLISHING', container_id='container')
        self.runner.fail(job['id'], RemoteError('timeout'))
        self.assertEqual(self.job()['status'], 'NEEDS_REVIEW')
        self.runner.recover()
        self.assertEqual(self.job()['status'], 'NEEDS_REVIEW')

    def test_restart_recovers_local_but_not_post(self):
        self.runner.receive(self.update())
        job = self.job()
        self.store.change(job['id'], 'PREPARING')
        self.runner.recover()
        self.assertEqual(self.job()['status'], 'QUEUED')
        self.store.change(job['id'], 'CREATING_CONTAINER')
        self.runner.recover()
        self.assertEqual(self.job()['status'], 'NEEDS_REVIEW')

    def test_removed_user_is_cancelled(self):
        self.runner.receive(self.update())
        self.config.users.write_text('{"allowed_user_ids":[]}')
        self.runner.process(self.job())
        self.assertEqual(self.job()['status'], 'CANCELLED')

    def test_timeout_during_actual_publish_call_preserves_container(self):
        self.runner.receive(self.update())
        self.runner.download = self.fake_download
        self.runner.ig = Mock()
        self.runner.ig.call.side_effect = [
            {'id': 'container'}, {'status_code': 'FINISHED'}, RemoteError('timeout')]
        with patch('app.runner.prepare_video', side_effect=self.fake_prepare), patch('app.runner.verify_public'):
            try:
                self.runner.process(self.job())
            except RemoteError as error:
                self.runner.fail(self.job()['id'], error)
        self.assertEqual(self.job()['status'], 'NEEDS_REVIEW')
        self.assertEqual(self.job()['container_id'], 'container')
        self.assertIsNone(self.job()['media_id'])
        self.assertEqual(self.runner.ig.call.call_count, 3)

    def test_config_container_paths_and_optional_version(self):
        env = {
            'TELEGRAM_BOT_TOKEN':'123:fake', 'IG_ACCESS_TOKEN':'fake',
            'IG_USER_ID':'999', 'IG_EXPECTED_USERNAME':'example', 'GRAPH_API_VERSION':'v99.0',
            'DATA_DIR':str(self.config.data), 'PUBLIC_MEDIA_DIR':str(self.config.public),
            'PUBLIC_MEDIA_BASE_URL':'https://example.com/media',
            'TELEGRAM_USERS_FILE':str(self.config.users), 'PUBLISH_ENABLED':'false'}
        with patch.dict('os.environ', env, clear=True), patch('app.config.load_env'):
            config = Config.load()
            self.assertFalse(config.publish)
            self.assertEqual(config.public, self.config.public)
            self.assertEqual(Instagram(config).base, 'https://graph.facebook.com/v99.0')
        env['GRAPH_API_VERSION'] = ''
        with patch.dict('os.environ', env, clear=True), patch('app.config.load_env'):
            config = Config.load()
            self.assertEqual(config.version, '')
            self.assertEqual(Instagram(config).base, 'https://graph.facebook.com')
        del env['GRAPH_API_VERSION']
        with patch.dict('os.environ', env, clear=True), patch('app.config.load_env'):
            self.assertEqual(Config.load().version, '')
        env['GRAPH_API_VERSION'] = 'incorrecta'
        with patch.dict('os.environ', env, clear=True), patch('app.config.load_env'):
            with self.assertRaises(RuntimeError):
                Config.load()

    def test_published_notification_failure_does_not_requeue(self):
        self.run_pipeline()
        with patch('app.runner.telegram', side_effect=__import__('scripts.telegram_receive', fromlist=['APIError']).APIError(500, 'error')):
            self.runner.flush_notifications()
        self.assertEqual(self.job()['status'], 'PUBLISHED')
        self.assertTrue(self.store.rows('SELECT * FROM outbox WHERE attempts>0'))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg no instalado')
    def test_real_horizontal_video_conversion(self):
        source = Path(self.temp.name) / 'source.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'testsrc2=size=320x180:rate=24', '-t', '3.2', '-c:v', 'mpeg4',
                        str(source)], check=True)
        ready = prepare_video(source)
        video = probe(ready)['streams'][0]
        self.assertEqual((video['width'], video['height']), (320, 180))
        self.assertEqual(video['codec_name'], 'h264')
        self.assertEqual(video['pix_fmt'], 'yuv420p')
        self.assertTrue(source.exists())


if __name__ == '__main__':
    unittest.main()
