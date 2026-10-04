import json
import queue
import threading
import time
import uuid
from dataclasses import dataclass

import httpx

from flight_session import auth_headers

@dataclass(frozen=True)
class GachaUploadTask:
    event_name: str
    nickname: str
    count: int
    gacha_index: int
    character_list: tuple[str, ...]
    request_id: str


@dataclass(frozen=True)
class GachaStateTask:
    event_name: str
    record_id: int
    is_revoked: bool


@dataclass(frozen=True)
class GachaMoveTask:
    event_name: str
    record_id: int
    action: str


class GachaUploadQueue:
    def __init__(
        self,
        client,
        url,
        login_token,
        *,
        move_url=None,
        restore_url=None,
        revoke_url=None,
        max_attempts=3,
        retry_delay=0.5,
        on_success=None,
        on_failure=None,
        daemon=False,
    ):
        if max_attempts < 1:
            raise ValueError("max_attempts 必须大于等于 1")
        self.client = client
        self.url = url
        self.login_token = login_token
        self.move_url = move_url
        self.restore_url = restore_url
        self.revoke_url = revoke_url
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
            daemon=daemon,
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
            request_id=str(uuid.uuid4()),
        )
        self._put(task)
        return task

    def restore(self, event_name, record_id):
        if self.restore_url is None:
            raise RuntimeError("恢复接口尚未配置")
        task = GachaStateTask(
            event_name=event_name,
            record_id=record_id,
            is_revoked=False,
        )
        self._put(task)
        return task

    def revoke(self, event_name, record_id):
        if self.revoke_url is None:
            raise RuntimeError("撤销接口尚未配置")
        task = GachaStateTask(
            event_name=event_name,
            record_id=record_id,
            is_revoked=True,
        )
        self._put(task)
        return task

    def move(self, event_name, record_id, action):
        if self.move_url is None:
            raise RuntimeError("记录排序接口尚未配置")
        if action not in {"first", "last", "previous", "next"}:
            raise ValueError("不支持的记录排序操作")
        task = GachaMoveTask(
            event_name=event_name,
            record_id=record_id,
            action=action,
        )
        self._put(task)
        return task

    def _put(self, task):
        with self._lock:
            if self._closed:
                raise RuntimeError("上传队列已经关闭")
            self._queue.put(task)

    def close(self, wait=True, timeout=None):
        with self._lock:
            if not self._closed:
                self._closed = True
                self._queue.put(self._sentinel)
        if wait and self._worker is not threading.current_thread():
            self._worker.join(timeout=timeout)
        return not self._worker.is_alive()

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
                if isinstance(task, GachaUploadTask):
                    url = self.url
                    payload = {
                        "event_name": task.event_name,
                        "nickname": task.nickname,
                        "count": task.count,
                        "gacha_index": task.gacha_index,
                        "character_json": json.dumps(
                            task.character_list,
                            ensure_ascii=False,
                        ),
                        "request_id": task.request_id,
                    }
                elif isinstance(task, GachaStateTask):
                    url = self.revoke_url if task.is_revoked else self.restore_url
                    payload = {
                        "event_name": task.event_name,
                        "record_id": task.record_id,
                    }
                else:
                    url = self.move_url
                    payload = {
                        "event_name": task.event_name,
                        "record_id": task.record_id,
                        "action": task.action,
                    }
                response = self.client.post(
                    url,
                    headers={**auth_headers(self.login_token), "Content-Type": "application/json"},
                    json=payload,
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
