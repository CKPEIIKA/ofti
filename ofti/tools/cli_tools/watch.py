from __future__ import annotations

from ofti.tools import watch_service as service

signal = service.signal

jobs_payload = service.jobs_payload
log_tail_payload = service.log_tail_payload
log_tail_payload_for_job = service.log_tail_payload_for_job
stop_payload = service.stop_payload
pause_payload = service.pause_payload
resume_payload = service.resume_payload
external_watch_payload = service.external_watch_payload
external_watch_start_payload = service.external_watch_start_payload
external_watch_status_payload = service.external_watch_status_payload
external_watch_attach_payload = service.external_watch_attach_payload
external_watch_stop_payload = service.external_watch_stop_payload
_signal_by_name = service._signal_by_name
_select_jobs = service._select_jobs
_set_job_status = service._set_job_status
