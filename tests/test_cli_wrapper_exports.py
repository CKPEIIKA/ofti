from __future__ import annotations

from ofti.tools import knife_service, plot_service, watch_service
from ofti.tools.cli_tools import knife, plot, watch


def test_plot_wrapper_exports_service_functions() -> None:
    assert plot.metrics_payload is plot_service.metrics_payload
    assert plot.residuals_payload is plot_service.residuals_payload


def test_watch_wrapper_exports_service_functions() -> None:
    assert watch.jobs_payload is watch_service.jobs_payload
    assert watch.log_tail_payload is watch_service.log_tail_payload
    assert watch.stop_payload is watch_service.stop_payload
    assert watch.pause_payload is watch_service.pause_payload
    assert watch.resume_payload is watch_service.resume_payload
    assert watch.external_watch_payload is watch_service.external_watch_payload
    assert watch.external_watch_start_payload is watch_service.external_watch_start_payload
    assert watch.external_watch_status_payload is watch_service.external_watch_status_payload
    assert watch.external_watch_attach_payload is watch_service.external_watch_attach_payload
    assert watch.external_watch_stop_payload is watch_service.external_watch_stop_payload


def test_knife_wrapper_exports_service_functions() -> None:
    assert knife.current_payload is knife_service.current_payload
    assert knife.status_payload is knife_service.status_payload
    assert knife.compare_payload is knife_service.compare_payload
    assert knife.converge_payload is knife_service.converge_payload
    assert knife.stability_payload is knife_service.stability_payload
