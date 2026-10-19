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


if __name__ == "__main__":
    unittest.main()
