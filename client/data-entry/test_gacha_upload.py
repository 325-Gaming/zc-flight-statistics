import json
import unittest

import httpx

from gacha_upload import GachaUploadQueue


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
        self.assertTrue(all("image_b64" not in request for request in requests))

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
