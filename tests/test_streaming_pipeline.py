import pytest
import asyncio
from streaming_pipeline import StreamingPipelineConsumer
from workflow_base import WorkflowTask, WorkflowContext, CancellationToken

class DummyWorkflowManager:
    def __init__(self):
        self.cancel_tokens = {}

    def get_cancel_token(self, task_id):
        if task_id not in self.cancel_tokens:
            self.cancel_tokens[task_id] = CancellationToken()
        return self.cancel_tokens[task_id]

    async def save_and_broadcast(self, event_type, task):
        pass

    async def calculate_overall_progress(self, task):
        pass

@pytest.mark.asyncio
async def test_streaming_pipeline_consumer_lifecycle():
    dummy_manager = DummyWorkflowManager()
    task = WorkflowTask(
        comic_title="Test Comic",
        comic_url="https://comic.naver.com/test",
        from_episode=1,
        to_episode=3,
        payload={"streaming_pipeline": True},
        id="test_stream"
    )
    task.artifacts["download_dir"] = "non_existent_test_dir"
    context = WorkflowContext(task, {}, dummy_manager)
    consumer = StreamingPipelineConsumer(context)
    
    assert not consumer._is_running
    consumer.start()
    assert consumer._is_running

    # Enqueue a dummy episode
    await consumer.enqueue_episode(999)
    # wait_all should process the queue and cleanly stop
    await consumer.wait_all()
    assert not consumer._is_running
    assert consumer.queue.empty()
