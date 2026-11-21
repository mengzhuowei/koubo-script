"""页面和对话共用的脚本任务入队规则。"""

from threading import Lock

from repositories import jobs_repo, research_cards_repo

_lock = Lock()


def request_script(topic_id: int, platform: str, format: str, duration: int) -> tuple[str, int | None]:
    with _lock:
        for job in jobs_repo.list_active_jobs_by_type("generate_script"):
            if (job.get("payload") or {}).get("topic_id") == topic_id:
                return "script_active", job["id"]

        if not research_cards_repo.get_latest_card_for_topic(topic_id):
            if research_cards_repo.has_active_research_job(topic_id):
                return "research_active", None
            job_id = jobs_repo.enqueue("generate_research_card", {"topic_id": topic_id})
            return "research_queued", job_id

        job_id = jobs_repo.enqueue("generate_script", {
            "topic_id": topic_id, "platform": platform, "format": format, "duration": duration,
        })
        return "script_queued", job_id
