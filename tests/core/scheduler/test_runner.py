import unittest
from unittest.mock import MagicMock, patch

from core.scheduler import runner


class TestAddIntervalJob(unittest.TestCase):
    def test_registers_a_non_overlapping_coalescing_interval_job(self):
        scheduler = MagicMock()

        async def job(bot):
            return None

        with patch.object(runner, "_scheduler", scheduler):
            runner.add_interval_job(job, 2, ["bot"])

        scheduler.add_job.assert_called_once_with(
            job, "interval", minutes=2, args=["bot"], max_instances=1, coalesce=True)

    def test_args_default_to_an_empty_list(self):
        scheduler = MagicMock()
        with patch.object(runner, "_scheduler", scheduler):
            runner.add_interval_job(print, 1)
        self.assertEqual(scheduler.add_job.call_args.kwargs["args"], [])

    def test_requires_a_started_scheduler(self):
        with patch.object(runner, "_scheduler", None), self.assertRaises(RuntimeError):
            runner.add_interval_job(print, 1)


class TestStartScheduler(unittest.TestCase):
    def test_jobs_use_the_configured_times(self):
        scheduler = MagicMock()
        with patch.object(runner, "AsyncIOScheduler", return_value=scheduler), \
             patch.object(runner.config, "REPOSTS_TIME", (8, 15)), \
             patch.object(runner.config, "RECAP_TIME", (17, 30)), \
             patch.object(runner.config, "ARCHIVE_IMAGES_TIME", (22, 0)), \
             patch.object(runner.config, "ARCHIVE_LOGS_TIME", (1, 5)):
            runner.start_scheduler("bot")
        times = [(c.kwargs["hour"], c.kwargs["minute"]) for c in scheduler.add_job.call_args_list]
        self.assertEqual(times, [(8, 15), (17, 30), (22, 0), (1, 5)])
        scheduler.start.assert_called_once()


class TestAddCronJob(unittest.TestCase):
    def test_registers_a_daily_job_at_the_given_time(self):
        scheduler = MagicMock()
        with patch.object(runner, "_scheduler", scheduler):
            runner.add_cron_job(print, 23, 59, ["bot"])
        scheduler.add_job.assert_called_once_with(print, "cron", hour=23, minute=59, args=["bot"])

    def test_args_default_to_an_empty_list(self):
        scheduler = MagicMock()
        with patch.object(runner, "_scheduler", scheduler):
            runner.add_cron_job(print, 1, 2)
        self.assertEqual(scheduler.add_job.call_args.kwargs["args"], [])

    def test_requires_a_started_scheduler(self):
        with patch.object(runner, "_scheduler", None), self.assertRaises(RuntimeError):
            runner.add_cron_job(print, 1, 2)


if __name__ == "__main__":
    unittest.main()
