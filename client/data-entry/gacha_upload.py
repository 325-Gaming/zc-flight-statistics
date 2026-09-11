import json
import queue
import threading
import time
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class GachaUploadTask:
    event_name: str
    nickname: str
    count: int
    gacha_index: int
    character_list: tuple[str, ...]


class GachaUploadQueue:
    def __init__(
        self,
        client,
        url,
        login_token,
        *,
        max_attempts=3,
        retry_delay=0.5,
        on_success=None,
        on_failure=None,
    ):
        if max_attempts < 1:
            raise ValueError("max_attempts 必须大于等于 1")
        self.client = client
        self.url = url
        self.login_token = login_token
        self.max_attempts = max_attempts
        self.retry_delay = retry_delay
        self.on_success = on_success
        self.on_failure = on_failure
        self._queue = queue.Queue()
        self._closed = False
        self._lock = threading.Lock()
        self._sentinel = object()
        self._worker = threading.Thread(
            target=self._run,
            name="gacha-upload",
            daemon=False,
        )
        self._worker.start()

    def submit(
        self,
        event_name,
        nickname,
        count,
        gacha_index,
        character_list,
    ):
        task = GachaUploadTask(
            event_name=event_name,
            nickname=nickname,
            count=count,
            gacha_index=gacha_index,
            character_list=tuple(character_list),
        )
        with self._lock:
            if self._closed:
                raise RuntimeError("上传队列已经关闭")
            self._queue.put(task)
        return task

    def close(self, wait=True):
        with self._lock:
            if not self._closed:
                self._closed = True
                self._queue.put(self._sentinel)
        if wait and self._worker is not threading.current_thread():
            self._worker.join()

    @property
    def pending_count(self):
        with self._queue.mutex:
            sentinel_count = 1 if self._closed else 0
            return max(0, self._queue.unfinished_tasks - sentinel_count)

    def _run(self):
        while True:
            task = self._queue.get()
            try:
                if task is self._sentinel:
                    return
                self._upload_with_retry(task)
            except Exception as error:
                if self.on_failure is not None:
                    self.on_failure(task, error)
            finally:
                self._queue.task_done()

    def _upload_with_retry(self, task):
        last_error = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.client.post(
                    self.url,
                    headers={
                        "Authorization": f"Bearer {self.login_token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "event_name": task.event_name,
                        "nickname": task.nickname,
                        "count": task.count,
                        "gacha_index": task.gacha_index,
                        "character_json": json.dumps(
                            task.character_list,
                            ensure_ascii=False,
                        ),
                    },
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                last_error = error
                if error.response.status_code < 500:
                    break
            except httpx.HTTPError as error:
                last_error = error
            else:
                if self.on_success is not None:
                    self.on_success(task, response)
                return

            if attempt < self.max_attempts:
                time.sleep(self.retry_delay * attempt)

        raise last_error
