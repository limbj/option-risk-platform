from celery import shared_task

from apps.valuations.worker import execute_chunk


@shared_task(acks_late=True, reject_on_worker_lost=True, ignore_result=True)
def calculate_chunk(chunk_id):
    return execute_chunk(chunk_id)
