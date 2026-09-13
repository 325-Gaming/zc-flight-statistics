import json
import unittest

import httpx

from gacha_upload import GachaMoveTask, GachaStateTask, GachaUploadQueue


class GachaUploadQueueTests(unittest.TestCase):
    def test_uploads_tasks_in_order_without_images(self):
        requests = []

        def handler(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={"status": "success"})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            upload_queue = GachaUploadQueue(client, "https://example.test", "token")
            upload_queue.submit("event", "user", 1, 1, ["三星干员"])
            upload_queue.submit("event", "user", 1, 2, ["四星干员"])
            upload_queue.close()

        self.assertEqual([request["gacha_index"] for request in requests], [1, 2])
        self.assertTrue(all(request["request_id"] for request in requests))
        self.assertTrue(all("image_b64" not in request for request in requests))

    def test_uses_same_request_id_during_retries(self):
        request_ids = []

        def handler(request):
            payload = json.loads(request.content)
            request_ids.append(payload["request_id"])
            status_code = 500 if len(request_ids) == 1 else 200
            return httpx.Response(status_code)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            upload_queue = GachaUploadQueue(
                client,
                "https://example.test/submit",
                "token",
                max_attempts=2,
                retry_delay=0,
            )
            upload_queue.submit("event", "user", 1, 1, ["三星干员"])
            upload_queue.close()

        self.assertEqual(len(set(request_ids)), 1)

    def test_queues_record_move(self):
        requests = []

        def handler(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            upload_queue = GachaUploadQueue(
                client,
                "https://example.test/submit",
                "token",
                move_url="https://example.test/move-record",
            )
            task = upload_queue.move("event", 13, "last")
            upload_queue.close()

        self.assertIsInstance(task, GachaMoveTask)
        self.assertEqual(
            requests,
            [{"event_name": "event", "record_id": 13, "action": "last"}],
        )

    def test_queues_revoke_and_restore_in_order(self):
        requests = []

        def handler(request):
            requests.append((request.url.path, json.loads(request.content)))
            return httpx.Response(200)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            upload_queue = GachaUploadQueue(
                client,
                "https://example.test/submit",
                "token",
                revoke_url="https://example.test/revoke",
                restore_url="https://example.test/restore",
            )
            revoked = upload_queue.revoke("event", 12)
            restored = upload_queue.restore("event", 12)
            upload_queue.close()

        self.assertIsInstance(revoked, GachaStateTask)
        self.assertTrue(revoked.is_revoked)
        self.assertFalse(restored.is_revoked)
        self.assertEqual(
            [path for path, _payload in requests],
            ["/revoke", "/restore"],
        )
        self.assertTrue(all(payload["record_id"] == 12 for _, payload in requests))

    def test_retries_server_errors_and_continues_with_next_task(self):
        attempts = []
        failures = []

        def handler(request):
            payload = json.loads(request.content)
            attempts.append(payload["gacha_index"])
            status_code = 500 if payload["gacha_index"] == 1 else 200
            return httpx.Response(status_code)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            upload_queue = GachaUploadQueue(
                client,
                "https://example.test",
                "token",
                max_attempts=2,
                retry_delay=0,
                on_failure=lambda task, error: failures.append(task.gacha_index),
            )
            upload_queue.submit("event", "user", 1, 1, ["三星干员"])
            upload_queue.submit("event", "user", 1, 2, ["四星干员"])
            upload_queue.close()

        self.assertEqual(attempts, [1, 1, 2])
        self.assertEqual(failures, [1])

    def test_rejects_new_tasks_after_close(self):
        with httpx.Client(transport=httpx.MockTransport(lambda request: None)) as client:
            upload_queue = GachaUploadQueue(client, "https://example.test", "token")
            upload_queue.close()
            with self.assertRaisesRegex(RuntimeError, "已经关闭"):
                upload_queue.submit("event", "user", 1, 1, [])


if __name__ == "__main__":
    unittest.main()
