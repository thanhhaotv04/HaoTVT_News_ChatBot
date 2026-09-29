from pathlib import Path


def test_daily_workflow_has_backup_schedules_and_delivery_deduplication():
    workflow = Path(".github/workflows/daily_news.yml").read_text(encoding="utf-8")
    backup = Path(".github/workflows/daily_news_backup.yml").read_text(encoding="utf-8")

    assert "cron: '30 23 * * *'" in workflow
    assert "workflow_call:" in workflow
    assert "cron: '40 23 * * *'" in backup
    assert "cron: '50 23 * * *'" in backup
    assert "uses: ./.github/workflows/daily_news.yml" in backup
    assert "daily-news-sent-${{ steps.delivery-date.outputs.date }}" in workflow
    assert "steps.delivery-cache.outputs.cache-hit != 'true'" in workflow
