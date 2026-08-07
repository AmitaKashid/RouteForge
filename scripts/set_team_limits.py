"""CLI tool to configure per-team operational limits and monthly USD budgets."""

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from routeforge.storage.database import DatabaseManager
from routeforge.storage.models import TeamLimitsModel, TeamModel


async def async_main(
    team_id: str,
    requests_per_minute: int,
    tokens_per_minute: int,
    monthly_budget_usd: Decimal,
) -> int:
    if requests_per_minute <= 0:
        print("Error: --requests-per-minute must be positive (> 0).", file=sys.stderr)
        return 1
    if tokens_per_minute <= 0:
        print("Error: --tokens-per-minute must be positive (> 0).", file=sys.stderr)
        return 1
    if monthly_budget_usd < Decimal("0"):
        print("Error: --monthly-budget-usd must be non-negative (>= 0).", file=sys.stderr)
        return 1

    db_manager = DatabaseManager()
    try:
        async with db_manager.session_factory() as session:
            # 1. Verify team exists
            stmt = select(TeamModel).where(TeamModel.team_id == team_id)
            result = await session.execute(stmt)
            team = result.scalar_one_or_none()

            if team is None:
                print(f"Error: Team '{team_id}' does not exist.", file=sys.stderr)
                return 1

            # 2. Check existing limits
            stmt_limits = select(TeamLimitsModel).where(TeamLimitsModel.team_id == team_id)
            limits_res = await session.execute(stmt_limits)
            limits = limits_res.scalar_one_or_none()

            now = datetime.now(UTC)
            if limits is None:
                limits = TeamLimitsModel(
                    team_id=team_id,
                    requests_per_minute=requests_per_minute,
                    tokens_per_minute=tokens_per_minute,
                    monthly_budget_usd=monthly_budget_usd,
                    active=True,
                    created_at=now,
                    updated_at=now,
                )
                session.add(limits)
            else:
                limits.requests_per_minute = requests_per_minute
                limits.tokens_per_minute = tokens_per_minute
                limits.monthly_budget_usd = monthly_budget_usd
                limits.updated_at = now

            await session.commit()

        print("=== RouteForge Team Limits Configured ===")
        print(f"Team ID:              {team_id}")
        print(f"Requests / Minute:    {requests_per_minute}")
        print(f"Tokens / Minute:      {tokens_per_minute}")
        print(f"Monthly Budget USD:   ${monthly_budget_usd:.8f}")
        print(f"Active:               {limits.active}")
        print(f"Updated At:           {limits.updated_at.isoformat()}")
        return 0
    finally:
        await db_manager.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Configure operational rate limits and monthly budget for a RouteForge team."
    )
    parser.add_argument("--team-id", required=True, help="Existing Team ID")
    parser.add_argument(
        "--requests-per-minute",
        type=int,
        required=True,
        help="Allowed requests per minute (must be > 0)",
    )
    parser.add_argument(
        "--tokens-per-minute",
        type=int,
        required=True,
        help="Allowed estimated tokens per minute (must be > 0)",
    )
    parser.add_argument(
        "--monthly-budget-usd",
        type=str,
        required=True,
        help="Monthly USD budget cap (e.g. 25.00)",
    )

    args = parser.parse_args()

    try:
        budget_dec = Decimal(args.monthly_budget_usd)
    except InvalidOperation:
        print("Error: --monthly-budget-usd must be a valid numeric decimal.", file=sys.stderr)
        sys.exit(1)

    exit_code = asyncio.run(
        async_main(
            team_id=args.team_id,
            requests_per_minute=args.requests_per_minute,
            tokens_per_minute=args.tokens_per_minute,
            monthly_budget_usd=budget_dec,
        )
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
