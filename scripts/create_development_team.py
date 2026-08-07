"""CLI script to create or reuse a development team and issue an API key."""

import argparse
import asyncio

from routeforge.storage.database import DatabaseManager
from routeforge.storage.records import (
    create_api_key_record,
    create_or_get_team,
    generate_api_key,
)


async def async_main(team_id: str, display_name: str) -> None:
    db = DatabaseManager()
    try:
        async with db.session_factory() as session:
            team = await create_or_get_team(
                session=session,
                team_id=team_id,
                display_name=display_name,
            )
            full_key, key_prefix, key_hash = generate_api_key()
            await create_api_key_record(
                session=session,
                team_id=team.team_id,
                key_prefix=key_prefix,
                key_hash=key_hash,
                active=True,
            )

        print("=== RouteForge Development Team & API Key Issued ===")
        print(f"Team ID:      {team.team_id}")
        print(f"Display Name: {team.display_name}")
        print(f"Key Prefix:   {key_prefix}")
        print(f"API Key:      {full_key}")
        print(
            "\nWARNING: Save this API key now! "
            "It is stored as a SHA-256 digest and CANNOT be recovered."
        )
    finally:
        await db.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create development team and API key.")
    parser.add_argument("--team-id", default="team-dev", help="Unique team ID string")
    parser.add_argument("--name", default="Development Team", help="Display name for team")
    args = parser.parse_args()

    asyncio.run(async_main(args.team_id, args.name))


if __name__ == "__main__":
    main()
