import asyncio
import unittest

from backend.services.turn_coordinator import TurnCoordinator


class TurnCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_turns_share_one_operation(self):
        coordinator = TurnCoordinator()
        calls = 0
        started = asyncio.Event()
        release = asyncio.Event()

        async def operation():
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return {"description": "同一结果"}

        first = asyncio.create_task(coordinator.execute(
            character_id="char-1",
            turn_id="turn-1",
            kind="environment",
            operation=operation,
        ))
        await started.wait()
        second = asyncio.create_task(coordinator.execute(
            character_id="char-1",
            turn_id="turn-1",
            kind="environment",
            operation=operation,
        ))
        await asyncio.sleep(0)
        release.set()
        first_result, second_result = await asyncio.gather(first, second)
        self.assertEqual(first_result, second_result)
        self.assertEqual(calls, 1)
        status = coordinator.get_status("char-1", "turn-1")
        self.assertEqual(status.shared_waiters, 1)
        self.assertTrue(status.recovered)

    async def test_different_turns_for_same_character_are_serial(self):
        coordinator = TurnCoordinator()
        active = 0
        max_active = 0
        order = []

        async def operation(name):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            order.append(f"start-{name}")
            await asyncio.sleep(0.02)
            order.append(f"end-{name}")
            active -= 1
            return {"turn": name}

        results = await asyncio.gather(
            coordinator.execute(
                character_id="char-1",
                turn_id="turn-a",
                kind="environment",
                operation=lambda: operation("a"),
            ),
            coordinator.execute(
                character_id="char-1",
                turn_id="turn-b",
                kind="npc_dialogue",
                operation=lambda: operation("b"),
            ),
        )
        self.assertEqual(max_active, 1)
        self.assertEqual(order, ["start-a", "end-a", "start-b", "end-b"])
        self.assertEqual([item["turn"] for item in results], ["a", "b"])

    async def test_cancelled_waiter_does_not_cancel_authoritative_turn(self):
        coordinator = TurnCoordinator()
        started = asyncio.Event()
        release = asyncio.Event()

        async def operation():
            started.set()
            await release.wait()
            return {"description": "断线后完成"}

        disconnected = asyncio.create_task(coordinator.execute(
            character_id="char-1",
            turn_id="turn-recover",
            kind="environment",
            operation=operation,
        ))
        await started.wait()
        disconnected.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await disconnected
        retry = asyncio.create_task(coordinator.execute(
            character_id="char-1",
            turn_id="turn-recover",
            kind="environment",
            operation=operation,
        ))
        release.set()
        self.assertEqual(await retry, {"description": "断线后完成"})


if __name__ == "__main__":
    unittest.main()
