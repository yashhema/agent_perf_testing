"""Database seed script.

Creates default admin user and standard load profiles.
Run this after database migration to set up initial data.

Usage:
    python -m orchestrator.seed [--config config/orchestrator.yaml]
"""

import argparse
import logging
import sys

from sqlalchemy.orm import Session

from orchestrator.config.settings import load_config
from orchestrator.models.database import Base, init_db, get_session
from orchestrator.models.enums import AgentType, DiskType
from orchestrator.models.orm import (
    AgentORM,
    HardwareProfileORM,
    LoadProfileORM,
    UserORM,
)
from orchestrator.services.auth import hash_password
from orchestrator.services.rule_engine import apply_preset

logger = logging.getLogger(__name__)


def seed_admin_user(session: Session) -> None:
    """Create the default admin user if it doesn't exist."""
    existing = session.query(UserORM).filter(UserORM.username == "admin").first()
    if existing:
        logger.info("Admin user already exists, skipping")
        return

    admin = UserORM(
        username="admin",
        password_hash=hash_password("admin"),
        email="admin@orchestrator.local",
        role="admin",
        is_active=True,
    )
    session.add(admin)
    session.commit()
    logger.info("Created default admin user (username='admin', password='admin')")


def seed_load_profiles(session: Session) -> None:
    """Create standard load profiles if they don't exist."""
    profiles = [
        {
            "name": "low",
            "target_cpu_range_min": 20.0,
            "target_cpu_range_max": 40.0,
            "duration_sec": 300,
            "ramp_up_sec": 30,
        },
        {
            "name": "medium",
            "target_cpu_range_min": 40.0,
            "target_cpu_range_max": 60.0,
            "duration_sec": 600,
            "ramp_up_sec": 60,
        },
        {
            "name": "high",
            "target_cpu_range_min": 60.0,
            "target_cpu_range_max": 80.0,
            "duration_sec": 600,
            "ramp_up_sec": 60,
        },
    ]

    for profile_data in profiles:
        existing = session.query(LoadProfileORM).filter(
            LoadProfileORM.name == profile_data["name"]
        ).first()
        if existing:
            logger.info("Load profile '%s' already exists, skipping", profile_data["name"])
            continue

        lp = LoadProfileORM(**profile_data)
        session.add(lp)
        logger.info("Created load profile: %s", profile_data["name"])

    session.commit()


def seed_sample_agent(session: Session) -> None:
    """Create a sample agent with standard rules if it doesn't exist."""
    existing = session.query(AgentORM).filter(AgentORM.name == "CrowdStrike Falcon v7.1").first()
    if existing:
        logger.info("Sample agent already exists, skipping")
        return

    agent = AgentORM(
        name="CrowdStrike Falcon v7.1",
        vendor="CrowdStrike",
        agent_type=AgentType.edr,
        version="7.1",
        description="CrowdStrike Falcon EDR sensor for endpoint detection and response",
        process_patterns=["CSFalcon*", "falcon*"],
        service_patterns=["CSFalconService"],
        discovery_key="crowdstrike",
        is_active=True,
    )
    session.add(agent)
    session.flush()

    apply_preset(session, agent.id, "standard")
    logger.info("Created sample agent 'CrowdStrike Falcon v7.1' with standard rules")


def seed_all(session: Session) -> None:
    """Run all seed operations."""
    seed_admin_user(session)
    seed_load_profiles(session)
    seed_sample_agent(session)
    logger.info("Seeding complete")


def main():
    parser = argparse.ArgumentParser(description="Seed orchestrator database")
    parser.add_argument("--config", default="config/orchestrator.yaml", help="Config file path")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = load_config(args.config)
    init_db(config.database.url, echo=config.database.echo)

    session_gen = get_session()
    session = next(session_gen)
    try:
        seed_all(session)
    finally:
        try:
            next(session_gen)
        except StopIteration:
            pass


if __name__ == "__main__":
    main()
